#Requires -Version 5.1

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

<#
.SYNOPSIS
    Giljo HQ -- Windows One-Liner Installer

.DESCRIPTION
    Downloads, verifies, and installs Giljo HQ from the latest GitHub release.
    Handles prerequisite checking/installation, SHA256 verification, environment
    setup, and first-run launch.

    Quick install:
        irm giljo.ai/install.ps1 | iex

    Customized install:
        .\install.ps1 -InstallDir "C:\GiljoAI" -SkipPrereqs

.PARAMETER InstallDir
    Installation directory. Defaults to $HOME\GiljoAI_MCP.

.PARAMETER SkipPrereqs
    Skip prerequisite checks and installation.

.PARAMETER Update
    Update an existing installation to the latest version.
#>

param(
    [string]$InstallDir = "",
    [switch]$SkipPrereqs,
    [switch]$Update
)

$ErrorActionPreference = 'Stop'

# Disable PowerShell's IWR/IRM progress bar - it slows downloads 5-10x on Win PS 5.1
$ProgressPreference = 'SilentlyContinue'

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# GILJO_INSTALL_SOURCE -- LAN / self-hosted override (INF-5090)
#
# Default (env var unset or empty): release metadata is fetched from
#   https://api.github.com/repos/giljoai/giljo-hq/releases/latest
# which is the standard public GitHub path for CE installs.
#
# LAN / internal override: set this env var to the Gitea API base URL
# for the target repository BEFORE running the installer:
#   $env:GILJO_INSTALL_SOURCE = "http://YOUR-GITEA-HOST:3000/api/v1/repos/OWNER/REPO"
#
# When set, BOTH the release API endpoint AND any asset/tarball URLs are
# resolved relative to GILJO_INSTALL_SOURCE.  The Gitea v1 API is a
# GitHub-compatible superset, so the same JSON parsing code works for both.
#
# INF-0004 (installer hardening) will also touch this file.  This block is
# intentionally placed at the TOP of the source-URL section so that merge
# does not collide with INF-0004's atomic-extract / unified-log additions.
# ---------------------------------------------------------------------------
$script:GITHUB_REPO = "giljoai/giljo-hq"

if ($env:GILJO_INSTALL_SOURCE -and $env:GILJO_INSTALL_SOURCE.Trim() -ne "") {
    # Override: use the caller-supplied API base (e.g. LAN Gitea)
    $script:RELEASE_API_BASE  = $env:GILJO_INSTALL_SOURCE.TrimEnd('/')
    $script:GITHUB_API_URL    = "$script:RELEASE_API_BASE/releases/latest"
} else {
    # Default: standard public GitHub API — behavior UNCHANGED for customers
    $script:RELEASE_API_BASE  = "https://api.github.com/repos/$script:GITHUB_REPO"
    $script:GITHUB_API_URL    = "https://api.github.com/repos/$script:GITHUB_REPO/releases/latest"
}

# Optional auth header for self-hosted Gitea / GitHub-Enterprise mirrors that
# require a login for API and asset access. Set GILJO_INSTALL_TOKEN to a token.
# No-op for the public GitHub install path (token unset). (INF-6037)
$script:AUTH_HEADERS = @{}
if ($env:GILJO_INSTALL_TOKEN) {
    $script:AUTH_HEADERS = @{ Authorization = "token $($env:GILJO_INSTALL_TOKEN)" }
}

# Default to a dedicated subdir of the user's home (matches the -InstallDir doc's
# $HOME\GiljoAI_MCP), NOT $PWD. A bare "irm ... | iex" runs from $HOME, where $PWD
# both scattered venv/frontend/data across the profile root AND made the atomic
# staging dir a sibling in the admin-owned parent (C:\Users) -> permission crash. A
# home subdir is user-owned so staging-inside-target always creates. (INF-9102)
$script:DEFAULT_INSTALL   = Join-Path $HOME "GiljoAI_MCP"
$script:MIN_PYTHON_MAJOR  = 3
$script:MIN_PYTHON_MINOR  = 12
$script:MIN_NODE_MAJOR    = 22
$script:SERVER_PORT       = 7272
$script:BRAND_COLOR       = "Yellow"
$script:SUCCESS_COLOR     = "Green"
$script:ERROR_COLOR       = "Red"
$script:INFO_COLOR        = "Cyan"
$script:MUTED_COLOR       = "Gray"

# Unified install log (INF-0004 sub-task #5). A PowerShell transcript captures the
# WHOLE Phase-1..6 console session to a temp file from the very first action, so a
# crash in Phase 1 (before install.py's own install.log exists) is still diagnosable
# after the terminal is closed. Once the target dir is known it is appended (redacted)
# into <TargetDir>\install.log so the customer ends up with ONE continuous file.
$script:TranscriptPath    = Join-Path ([System.IO.Path]::GetTempPath()) "giljoai-install.log"
$script:ResolvedTargetDir = $null

# Redact credential-looking tokens before persisting the transcript to the install
# dir. Mirrors install.py's _SENSITIVE_PATTERNS so both halves of the unified log
# scrub the same shapes.
$script:SensitivePattern  = '(?i)(password|passwd|secret|token|key|credential)([=:\s]+)\S+'

# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

function Write-Banner {
    Write-Host ""
    Write-Host "    Giljo HQ Community Edition" -ForegroundColor Yellow
    Write-Host "    Windows Installer" -ForegroundColor $script:MUTED_COLOR
    Write-Host ""
}

function Write-Phase {
    param([string]$Number, [string]$Title)
    Write-Host ""
    Write-Host "  [$Number/5] $Title" -ForegroundColor $script:BRAND_COLOR
    Write-Host "  $('-' * (6 + $Title.Length))" -ForegroundColor $script:MUTED_COLOR
}

function Write-Step {
    param([string]$Message)
    Write-Host "    > $Message" -ForegroundColor $script:INFO_COLOR
}

function Write-Ok {
    param([string]$Message)
    Write-Host "    [OK] $Message" -ForegroundColor $script:SUCCESS_COLOR
}

function Write-Warn {
    param([string]$Message)
    Write-Host "    [!] $Message" -ForegroundColor $script:BRAND_COLOR
}

function Write-Fail {
    param([string]$Message)
    Write-Host "    [FAIL] $Message" -ForegroundColor $script:ERROR_COLOR
}

function Exit-WithError {
    param([string]$Message)
    Write-Host ""
    # Point the customer at the log FIRST so they can paste it when reporting the
    # issue, even if they close the terminal right after reading the error. (INF-0004 #5)
    if ($script:TranscriptPath) {
        Write-Host "    Full log: $script:TranscriptPath -- paste this if you report the issue" -ForegroundColor $script:INFO_COLOR
    }
    Write-Fail $Message
    Write-Host ""
    throw $Message
}

function Test-CommandExists {
    param([string]$Command)
    try {
        Get-Command $Command -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-RealCommand {
    <#
    .SYNOPSIS
        Like Test-CommandExists, but rejects Windows Store "App execution alias"
        stubs (...\WindowsApps\python.exe / node.exe). Those stubs satisfy
        Get-Command on a fresh Win11 even though nothing is installed -- running
        them just prints "Python was not found" and opens the Store. Treating the
        stub as "missing" lets winget install the real tool. (INF-6037)
    #>
    param([string]$Command)
    $c = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $c) { return $false }
    # Resolve the backing file for aliases/functions that wrap an executable.
    $source = $c.Source
    if ($c.CommandType -eq 'Application' -and $source -and ($source -like "*\WindowsApps\*")) {
        return $false
    }
    return $true
}

function Test-PortInUse {
    <#
    .SYNOPSIS
        True when something is already listening on a local TCP port.

        Used to pre-check 5432 before the winget PostgreSQL install, which pins
        --serverport 5432 and fails opaquely when the port is taken. A raw
        TcpClient is used rather than Test-NetConnection: it needs no elevation,
        adds no module load, and returns in milliseconds. (INF-9321)
    #>
    param(
        [int]$Port,
        [int]$TimeoutMs = 700
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-ParsedVersion {
    <#
    .SYNOPSIS
        Parses a version string like "Python 3.12.4" or "v20.11.0" and returns
        major, minor as integers.
    #>
    param([string]$VersionString)

    if ($VersionString -match '(\d+)\.(\d+)') {
        return @{
            Major = [int]$Matches[1]
            Minor = [int]$Matches[2]
        }
    }
    return $null
}

function Refresh-PathEnv {
    <#
    .SYNOPSIS
        Reloads PATH from the registry so newly installed tools are visible
        without restarting the shell.
    #>
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path    = "$machinePath;$userPath"
}

function Add-ToUserPath {
    <#
    .SYNOPSIS
        Persists a directory to the User PATH environment variable so it
        survives shell restarts. Also updates the current session's PATH.
        No-op if the directory is already present (case-insensitive match).
    #>
    param([Parameter(Mandatory=$true)][string]$Directory)

    if (-not (Test-Path $Directory)) { return }

    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }

    $entries = $userPath -split ';' | Where-Object { $_ -ne "" }
    $alreadyPresent = $entries | Where-Object { $_.TrimEnd('\') -ieq $Directory.TrimEnd('\') }

    if (-not $alreadyPresent) {
        $newUserPath = if ($userPath) { "$Directory;$userPath" } else { $Directory }
        [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
        Write-Ok "Added $Directory to User PATH (persisted)"
    }

    # Always update current session so the rest of the installer sees it.
    if (($env:PATH -split ';') -notcontains $Directory) {
        $env:PATH = "$Directory;$env:PATH"
    }
}

# ---------------------------------------------------------------------------
# Phase 1 -- Prerequisites
# ---------------------------------------------------------------------------

function Test-Prerequisites {
    Write-Phase "1" "Checking prerequisites"

    $missing = @()

    # -- Python --
    # Test-RealCommand (not Test-CommandExists): a fresh Win11 ships a Store
    # app-execution-alias stub for python.exe that satisfies Get-Command but is
    # not a real install. Treat the stub as missing so winget installs Python. (INF-6037)
    Write-Step "Checking Python..."
    if (Test-RealCommand "python") {
        $pyVersionRaw = & python --version 2>&1
        $pyVersion = Get-ParsedVersion $pyVersionRaw
        if ($pyVersion -and
            ($pyVersion.Major -gt $script:MIN_PYTHON_MAJOR -or
            ($pyVersion.Major -eq $script:MIN_PYTHON_MAJOR -and $pyVersion.Minor -ge $script:MIN_PYTHON_MINOR))) {
            Write-Ok "Python $($pyVersion.Major).$($pyVersion.Minor) found"
        } else {
            Write-Warn "Python found but version too old: $pyVersionRaw (need $($script:MIN_PYTHON_MAJOR).$($script:MIN_PYTHON_MINOR)+)"
            $missing += "python"
        }
    } else {
        Write-Warn "Python not found"
        $missing += "python"
    }

    # -- Node.js --
    # Test-RealCommand: same Store app-execution-alias trap as Python (node.exe). (INF-6037)
    Write-Step "Checking Node.js..."
    if (Test-RealCommand "node") {
        $nodeVersionRaw = & node --version 2>&1
        $nodeVersion = Get-ParsedVersion $nodeVersionRaw
        if ($nodeVersion -and $nodeVersion.Major -ge $script:MIN_NODE_MAJOR) {
            Write-Ok "Node.js $($nodeVersion.Major).$($nodeVersion.Minor) found"
        } else {
            Write-Warn "Node.js found but version too old: $nodeVersionRaw (need $($script:MIN_NODE_MAJOR)+)"
            $missing += "node"
        }
    } else {
        Write-Warn "Node.js not found"
        $missing += "node"
    }

    # -- Git --
    Write-Step "Checking Git..."
    if (Test-CommandExists "git") {
        $gitVersionRaw = & git --version 2>&1
        Write-Ok "Git found: $gitVersionRaw"
    } else {
        Write-Warn "Git not found"
        $missing += "git"
    }

    # -- PostgreSQL --
    Write-Step "Checking PostgreSQL..."
    $pgFound = $false

    # 1) Command on PATH
    if (Test-CommandExists "pg_isready") {
        Write-Ok "PostgreSQL found (pg_isready available)"
        $pgFound = $true
    }

    # 2) Windows service
    if (-not $pgFound) {
        $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
        if ($pgService) {
            Write-Ok "PostgreSQL service found: $($pgService.DisplayName)"
            $pgFound = $true
        }
    }

    # 3) Standard filesystem locations -- bin may not be on PATH yet
    if (-not $pgFound) {
        $pgBinCandidates = Get-ChildItem -Path "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue
        if ($pgBinCandidates) {
            $pgBinDir = Split-Path $pgBinCandidates[0].FullName -Parent
            Write-Ok "PostgreSQL found at $pgBinDir"
            Add-ToUserPath -Directory $pgBinDir
            $pgFound = $true
        }
    }

    # 4) winget package registry -- catches installs whose bin isn't on PATH and whose service is named oddly
    if (-not $pgFound -and (Test-CommandExists "winget")) {
        # --accept-source-agreements + --disable-interactivity are MANDATORY here:
        # on a fresh Windows, winget's first-run msstore source-agreement prompt
        # blocks on stdin, and under `irm ... | iex` there is no console to answer
        # it, so a bare `winget list` hangs forever. (INF-6037)
        $wingetList = & winget list --id PostgreSQL.PostgreSQL --exact --accept-source-agreements --disable-interactivity 2>&1 | Out-String
        if ($wingetList -match "PostgreSQL\.PostgreSQL") {
            Write-Ok "PostgreSQL found via winget package registry"
            $pgFound = $true
        }
    }

    if (-not $pgFound) {
        Write-Warn "PostgreSQL not detected"
        $missing += "postgresql"
    }

    if (@($missing).Count -eq 0) {
        Write-Ok "All prerequisites satisfied"
        return
    }

    # -- Install missing prerequisites --
    Write-Host ""
    Write-Step "Missing prerequisites: $($missing -join ', ')"

    $hasWinget = Test-CommandExists "winget"

    # Handle non-PostgreSQL items via winget.
    # @(...) forces array semantics so .Count works when the filter yields
    # 0 items ($null) or 1 item (scalar) -- both crash StrictMode otherwise.
    $wingetItems = @($missing | Where-Object { $_ -ne "postgresql" })

    if ($wingetItems.Count -gt 0) {
        if (-not $hasWinget) {
            Exit-WithError "winget is required to install missing prerequisites ($($wingetItems -join ', ')). Please install them manually or install winget first."
        }

        Write-Step "Installing missing packages via winget..."

        $wingetMap = @{
            "python" = "Python.Python.3.12"
            "node"   = "OpenJS.NodeJS.LTS"
            "git"    = "Git.Git"
        }

        foreach ($item in $wingetItems) {
            $packageId = $wingetMap[$item]
            Write-Step "Installing $packageId..."
            try {
                & winget install --id $packageId --accept-package-agreements --accept-source-agreements --silent --disable-interactivity 2>&1 | Out-Null
                Write-Ok "$item installed"
            } catch {
                Exit-WithError "Failed to install $item via winget. Please install manually and re-run this script."
            }
        }

        # Refresh PATH so newly installed tools are visible
        Refresh-PathEnv
        Write-Step "PATH refreshed after installations"
    }

    # Handle PostgreSQL via winget with user-provided settings
    if ($missing -contains "postgresql") {
        Write-Host ""
        Write-Host "    -------------------------------------------------------" -ForegroundColor $script:BRAND_COLOR
        Write-Host "    PostgreSQL will be installed automatically via winget." -ForegroundColor $script:BRAND_COLOR
        Write-Host "    -------------------------------------------------------" -ForegroundColor $script:BRAND_COLOR
        Write-Host ""

        if (-not $hasWinget) {
            Exit-WithError "winget is required to install PostgreSQL. Please install PostgreSQL manually from https://www.postgresql.org/download/windows/ and re-run this script."
        }

        # Port pre-check (INF-9321). The winget override below pins
        # --serverport 5432. If something else already holds that port the EDB
        # installer fails, and the only signal is a numeric winget exit code
        # several minutes later -- after the user has typed a password. Say it
        # up front, in words, before anything is installed.
        if (Test-PortInUse -Port 5432) {
            Exit-WithError "Port 5432 is already in use, and PostgreSQL must be installed on it.`nSomething is already listening there - most likely an existing PostgreSQL, or a Docker container publishing 5432.`nStop or reconfigure whatever holds port 5432, then re-run this script."
        }

        # A) PostgreSQL admin password + DB name.
        # Unattended (GILJO_UNATTENDED=1): read from env, no prompts. install.py
        # reads the same env vars for its own DB step. (INF-6037)
        if ($env:GILJO_UNATTENDED -eq "1") {
            $pgPw1 = $env:GILJO_PG_PASSWORD
            if ([string]::IsNullOrWhiteSpace($pgPw1)) {
                Exit-WithError "Unattended install requires GILJO_PG_PASSWORD for PostgreSQL setup."
            }
            if ([string]::IsNullOrWhiteSpace($env:GILJO_DB_NAME)) {
                $script:PG_DB_NAME = "giljo_mcp"
            } else {
                $script:PG_DB_NAME = $env:GILJO_DB_NAME
            }
            Write-Ok "PostgreSQL password from GILJO_PG_PASSWORD (unattended); database: $script:PG_DB_NAME"
        } else {
            Write-Host "    Choose a password for the PostgreSQL 'postgres' admin user." -ForegroundColor $script:INFO_COLOR
            Write-Host "    You will need this password again during application setup." -ForegroundColor $script:MUTED_COLOR
            Write-Host ""
            do {
                $pgSecure1 = Read-Host "    PostgreSQL admin password" -AsSecureString
                $pgSecure2 = Read-Host "    Confirm password" -AsSecureString

                $pgPw1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pgSecure1))
                $pgPw2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pgSecure2))

                if ([string]::IsNullOrWhiteSpace($pgPw1)) {
                    Write-Warn "Password cannot be empty."
                    $pgPwOk = $false
                } elseif ($pgPw1 -ne $pgPw2) {
                    Write-Warn "Passwords do not match. Try again."
                    $pgPwOk = $false
                } else {
                    $pgPwOk = $true
                }
            } while (-not $pgPwOk)
            Write-Ok "PostgreSQL password set"

            # B) Prompt for database name
            Write-Host ""
            Write-Host "    Choose the database name for Giljo HQ." -ForegroundColor $script:INFO_COLOR
            Write-Host "    Change this only if running multiple installations on the same server." -ForegroundColor $script:MUTED_COLOR
            $pgDbInput = Read-Host "    Database name [giljo_mcp]"
            if ([string]::IsNullOrWhiteSpace($pgDbInput)) {
                $script:PG_DB_NAME = "giljo_mcp"
            } else {
                $script:PG_DB_NAME = $pgDbInput
            }
            Write-Ok "Database name: $script:PG_DB_NAME"
        }

        # Install PostgreSQL via winget
        Write-Step "Installing PostgreSQL via winget..."
        try {
            # Build override as a single string for the EDB PostgreSQL installer.
            # Winget's --override passes this verbatim to the installer executable.
            $escapedPw = $pgPw1 -replace '"', '\"'
            $pgArgs = @(
                "install"
                "PostgreSQL.PostgreSQL.18"
                "--silent"
                "--accept-source-agreements"
                "--accept-package-agreements"
                "--disable-interactivity"
                "--override"
            )
            # Use Start-Process with a single-line ArgumentList string so the
            # override value (which contains spaces) stays as one token.
            $argLine = ($pgArgs -join " ") + " `"--mode unattended --unattendedmodeui none --superpassword $escapedPw --serverport 5432 --enable-components server,commandlinetools --disable-components pgAdmin,stackbuilder`""
            Write-Host ""
            Write-Host "    +==========================================================+" -ForegroundColor $script:BRAND_COLOR
            Write-Host "    |  PostgreSQL is installing silently - this takes 3-5      |" -ForegroundColor $script:BRAND_COLOR
            Write-Host "    |  minutes. Microsoft C++ dependencies may also install.   |" -ForegroundColor $script:BRAND_COLOR
            Write-Host "    |  Please wait and do not close this window.               |" -ForegroundColor $script:BRAND_COLOR
            Write-Host "    +==========================================================+" -ForegroundColor $script:BRAND_COLOR
            Write-Host ""
            $pgProc = Start-Process -FilePath "winget" -ArgumentList $argLine -Wait -PassThru -NoNewWindow
            # winget exit codes that mean "nothing to do, package already present":
            #   -1978335189 (0x8A15002B) APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE
            #   -1978335207 (0x8A150019) APPINSTALLER_CLI_ERROR_PACKAGE_ALREADY_INSTALLED
            $okCodes = @(0, -1978335189, -1978335207)
            if ($okCodes -notcontains $pgProc.ExitCode) {
                throw "winget exited with code $($pgProc.ExitCode)"
            }
            if ($pgProc.ExitCode -eq 0) {
                Write-Ok "PostgreSQL installed"
            } else {
                Write-Ok "PostgreSQL already installed (winget reports up-to-date)"
            }
        } catch {
            Exit-WithError "PostgreSQL installation failed: $_`nPlease install manually from https://www.postgresql.org/download/windows/ and re-run this script."
        }

        # Persist PostgreSQL bin to User PATH (survives shell restart)
        $pgBinPaths = @(
            "C:\Program Files\PostgreSQL\18\bin",
            "C:\Program Files\PostgreSQL\17\bin",
            "C:\Program Files\PostgreSQL\16\bin"
        )
        foreach ($p in $pgBinPaths) {
            if (Test-Path $p) {
                Add-ToUserPath -Directory $p
                break
            }
        }

        Refresh-PathEnv

        # Verify PostgreSQL is now available
        $pgNow = (Test-CommandExists "pg_isready") -or
                 (Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue)
        if (-not $pgNow) {
            Exit-WithError "PostgreSQL was installed but is not detected. Try restarting your terminal and re-running this script."
        }
        Write-Ok "PostgreSQL detected after install"
    }

    # Final verification of winget-installed items.
    # Test-RealCommand, NOT Test-CommandExists: the prereq check above already
    # treats a WindowsApps stub as missing, so verifying with the weaker test
    # would let the very stub we routed around satisfy the check -- winget could
    # fail, or land python somewhere behind the stub on PATH, and this gate would
    # still pass. The install then dies later, further from the cause. (INF-9321)
    #
    # Only these winget-installed items get the stricter test. Do NOT extend it to
    # the `winget` probes above: winget itself ships as an MSIX whose own launcher
    # lives in WindowsApps, so Test-RealCommand reports it missing and the
    # installer would abort on every machine that has it.
    foreach ($item in $wingetItems) {
        $cmd = switch ($item) {
            "python" { "python" }
            "node"   { "node" }
            "git"    { "git" }
        }
        if (-not (Test-RealCommand $cmd)) {
            Exit-WithError "$item was installed but is not usable from PATH (a Windows Store app-execution-alias stub may still be shadowing it). Please close and reopen your terminal, then re-run this script."
        }
    }

    Write-Ok "All prerequisites satisfied after installation"
}

# ---------------------------------------------------------------------------
# Phase 2 -- Download and verify
# ---------------------------------------------------------------------------

function Get-LatestRelease {
    Write-Phase "2" "Downloading latest release"

    # Fetch release metadata
    Write-Step "Fetching latest release info from GitHub..."
    try {
        $releaseInfo = Invoke-RestMethod -Uri $script:GITHUB_API_URL -Headers $script:AUTH_HEADERS -UseBasicParsing
    } catch {
        Exit-WithError "Failed to fetch release info from GitHub. Check your internet connection."
    }

    $version = $releaseInfo.tag_name -replace '^v', ''
    Write-Ok "Latest version: $version"

    # Find version-manifest.json asset
    $manifestAsset = $releaseInfo.assets | Where-Object { $_.name -eq "version-manifest.json" }
    if (-not $manifestAsset) {
        Exit-WithError "Release is missing version-manifest.json. This release may be malformed."
    }

    # Download and parse the manifest
    Write-Step "Downloading version manifest..."
    $manifestUrl = $manifestAsset.browser_download_url
    $manifestContent = Invoke-RestMethod -Uri $manifestUrl -Headers $script:AUTH_HEADERS -UseBasicParsing

    $tarballUrl = $manifestContent.tarball_url
    $expectedSha = $manifestContent.sha256

    if (-not $tarballUrl -or -not $expectedSha) {
        Exit-WithError "Version manifest is incomplete (missing tarball_url or sha256)."
    }

    # Download tarball
    $tarballName = "giljoai-mcp-$version.tar.gz"
    $tempDir     = Join-Path ([System.IO.Path]::GetTempPath()) "giljoai-install"
    if (-not (Test-Path $tempDir)) {
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
    }
    $tarballPath = Join-Path $tempDir $tarballName

    Write-Step "Downloading $tarballName..."
    try {
        Invoke-WebRequest -Uri $tarballUrl -OutFile $tarballPath -Headers $script:AUTH_HEADERS -UseBasicParsing
    } catch {
        Exit-WithError "Failed to download tarball from $tarballUrl"
    }
    Write-Ok "Downloaded to $tarballPath"

    # Verify SHA256
    Write-Step "Verifying SHA256 checksum..."
    $actualHash = (Get-FileHash -Path $tarballPath -Algorithm SHA256).Hash.ToLower()
    $expectedHash = $expectedSha.ToLower()

    if ($actualHash -ne $expectedHash) {
        Remove-Item -Path $tarballPath -Force -ErrorAction SilentlyContinue
        Exit-WithError "SHA256 mismatch! Expected: $expectedHash, Got: $actualHash. The download may be corrupted or tampered with."
    }
    Write-Ok "SHA256 verified: $actualHash"

    return @{
        Version     = $version
        TarballPath = $tarballPath
        TempDir     = $tempDir
    }
}

function Install-Release {
    param(
        [hashtable]$Release,
        [string]$TargetDir,
        [bool]$IsUpdate
    )

    # Ask for install directory if not provided
    if (-not $TargetDir) {
        $TargetDir = $script:DEFAULT_INSTALL
        if ($env:GILJO_UNATTENDED -eq "1") {
            # Unattended: take the dir from GILJO_INSTALL_DIR (or the default), no prompt. (INF-6037)
            if ($env:GILJO_INSTALL_DIR) { $TargetDir = $env:GILJO_INSTALL_DIR }
            Write-Ok "Install directory: $TargetDir (unattended)"
        }
        else {
        Write-Host ""
        Write-Host "    Install directory [$TargetDir]: " -ForegroundColor $script:INFO_COLOR -NoNewline
        $userInput = Read-Host
        if ($userInput) {
            $TargetDir = $userInput
        }
        }
    }

    # Resolve to absolute path
    $TargetDir = [System.IO.Path]::GetFullPath($TargetDir)

    # Back up config files before extraction if updating
    $backupDir = $null
    if ($IsUpdate) {
        Write-Step "Backing up configuration files..."
        $backupDir = Join-Path $Release.TempDir "config-backup"
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

        $configFiles = @(".env", "config.yaml")
        foreach ($f in $configFiles) {
            $src = Join-Path $TargetDir $f
            if (Test-Path $src) {
                Copy-Item -Path $src -Destination (Join-Path $backupDir $f) -Force
                Write-Ok "Backed up $f"
            }
        }
    }

    # Create or verify target directory
    if (-not (Test-Path $TargetDir)) {
        try {
            New-Item -ItemType Directory -Path $TargetDir -Force -ErrorAction Stop | Out-Null
        } catch {
            Exit-WithError "Cannot create install directory: ${TargetDir} -- check write permissions for its parent."
        }
        Write-Ok "Created directory: $TargetDir"
    }

    # Atomic extraction (INF-0004 sub-task #2): extract into a staging dir that is a
    # hidden CHILD of $TargetDir (NOT a sibling), so the final per-entry moves are
    # same-volume renames. A Ctrl+C / power-loss / AV-quarantine DURING the slow
    # extract only ever litters the staging child -- the live install is left
    # untouched, and a re-run cleans the stale staging dir. Install-time artifacts
    # (venv/, .env, config.yaml, data/, logs/) are NOT in the tarball, so the
    # per-entry swap replaces only release files and leaves user data intact.
    #
    # Why a child and not a sibling "$TargetDir.new": the default install dir is a
    # subdir of $HOME, whose parent (C:\Users) is admin-owned -- a standard user
    # cannot create a sibling there. $TargetDir is already created and user-owned,
    # so a child always creates and stays same-volume (preserves INF-0004's atomic
    # -rename guarantee -- do NOT stage on another volume). (INF-9102)
    $stagingDir = Join-Path $TargetDir ".giljo-staging-$PID"
    if (Test-Path $stagingDir) { Remove-Item -Recurse -Force $stagingDir -ErrorAction SilentlyContinue }
    # Preflight: prove the staging child is creatable in the chosen target BEFORE the
    # slow extract, so a bad target fails early with a clear, named message.
    try {
        New-Item -ItemType Directory -Path $stagingDir -Force -ErrorAction Stop | Out-Null
    } catch {
        Exit-WithError "Cannot create staging directory inside ${TargetDir} -- check write permissions for that path."
    }

    Write-Step "Extracting release to a staging area..."
    try {
        & tar -xzf $Release.TarballPath -C $stagingDir 2>&1 | Out-Null
    } catch {
        Remove-Item -Recurse -Force $stagingDir -ErrorAction SilentlyContinue
        Exit-WithError "Failed to extract release archive. Ensure 'tar' is available (Windows 10+ includes it), then re-run install.ps1."
    }
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        Remove-Item -Recurse -Force $stagingDir -ErrorAction SilentlyContinue
        Exit-WithError "Failed to extract release archive (tar exit code $LASTEXITCODE). Ensure 'tar' is available (Windows 10+ includes it), then re-run install.ps1."
    }

    Write-Step "Installing release files..."
    try {
        foreach ($entry in Get-ChildItem -LiteralPath $stagingDir -Force) {
            $dest = Join-Path $TargetDir $entry.Name
            if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
            Move-Item -LiteralPath $entry.FullName -Destination $dest
        }
    } catch {
        Remove-Item -Recurse -Force $stagingDir -ErrorAction SilentlyContinue
        Exit-WithError "Failed to install release files: $_`nIf the server is running, stop it and re-run install.ps1."
    }
    Remove-Item -Recurse -Force $stagingDir -ErrorAction SilentlyContinue
    Write-Ok "Extraction complete"

    # Restore backed-up config files
    if ($IsUpdate -and $backupDir) {
        Write-Step "Restoring configuration files..."
        $configFiles = @(".env", "config.yaml")
        foreach ($f in $configFiles) {
            $backup = Join-Path $backupDir $f
            if (Test-Path $backup) {
                Copy-Item -Path $backup -Destination (Join-Path $TargetDir $f) -Force
                Write-Ok "Restored $f"
            }
        }
    }

    # Write VERSION file
    $Release.Version | Out-File -FilePath (Join-Path $TargetDir "VERSION") -Encoding UTF8 -NoNewline

    # Clean up temp files
    Remove-Item -Path $Release.TarballPath -Force -ErrorAction SilentlyContinue | Out-Null

    # IMPORTANT: only return the string - no other pipeline output
    return $TargetDir
}

# ---------------------------------------------------------------------------
# Phase 3 -- Environment setup
# ---------------------------------------------------------------------------

function Initialize-Environment {
    param([string]$TargetDir)

    Write-Phase "3" "Setting up environment"

    $venvDir = Join-Path $TargetDir "venv"
    # Nested 2-arg Join-Path: Windows PowerShell 5.1 (the installer's target)
    # does not accept 3+ path segments in one Join-Path call. (INF-6037)
    $venvPython = Join-Path (Join-Path $venvDir "Scripts") "python.exe"
    $venvPip    = Join-Path (Join-Path $venvDir "Scripts") "pip.exe"

    # Create venv if it does not exist
    if (-not (Test-Path $venvPython)) {
        Write-Step "Creating Python virtual environment..."
        & python -m venv $venvDir
        Write-Ok "Virtual environment created"
    } else {
        Write-Ok "Virtual environment already exists"
    }

    # Upgrade pip. Let it stream (no --quiet / Out-Null) so the user sees progress
    # instead of a frozen-looking pause; --timeout 60 bounds each connection. (INF-0004 #4)
    Write-Step "Upgrading pip..."
    & $venvPython -m pip install --upgrade pip --timeout 60
    Write-Ok "pip upgraded"

    # Install Python dependencies. Streams live (the user previously saw a 2-3 min
    # silent pause) AND now FAILS LOUDLY: the old `--quiet 2>&1 | Out-Null` swallowed
    # both the output and the exit code, so a failed install was reported as success
    # and only surfaced later as a broken server. (INF-0004 #1/#4)
    $requirementsPath = Join-Path $TargetDir "requirements.txt"
    # INF-9057: requirements.lock ships with the release and pins the full
    # resolved dependency tree. Passed as a pip CONSTRAINTS file (-c) it pins
    # every package pip installs (platform-inapplicable entries are ignored),
    # so a breaking upstream release cannot break a fresh install. Its absence
    # (an older extracted release) is tolerated -- pip resolves the floors.
    $constraintsPath = Join-Path $TargetDir "requirements.lock"
    $constraintsArgs = @()
    if (Test-Path $constraintsPath) {
        $constraintsArgs = @("-c", $constraintsPath)
    }
    if (Test-Path $requirementsPath) {
        Write-Step "Installing Python dependencies (this may take a few minutes)..."
        & $venvPip install -r $requirementsPath @constraintsArgs --timeout 60
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            Exit-WithError "Installing Python dependencies failed (pip exit code $LASTEXITCODE). See the output above, then re-run install.ps1."
        }
        Write-Ok "Python dependencies installed"
    } else {
        Write-Warn "requirements.txt not found -- skipping pip install"
    }

    # Register giljo_mcp as importable package (editable install, idempotent).
    # Best-effort (non-fatal), but now visible rather than black-holed.
    $pyprojectPath = Join-Path $TargetDir "pyproject.toml"
    if (Test-Path $pyprojectPath) {
        & $venvPip install -e $TargetDir @constraintsArgs --timeout 60
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            Write-Warn "Editable install skipped (non-fatal) -- pip exit code $LASTEXITCODE"
        } else {
            Write-Ok "Package registered (editable install)"
        }
    }

    # Build frontend - use Start-Process to avoid irm|iex pipeline mangling npm
    $frontendDir = Join-Path $TargetDir "frontend"
    if (Test-Path (Join-Path $frontendDir "package.json")) {
        Write-Step "Installing frontend dependencies..."
        $npmPath = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
        if (-not $npmPath) { $npmPath = (Get-Command npm -ErrorAction SilentlyContinue).Source }
        if ($npmPath) {
            $npmLog = Join-Path $TargetDir "npm-build.log"
            $npmErrLog = Join-Path $TargetDir "npm-build-err.log"
            $proc1 = Start-Process -FilePath $npmPath -ArgumentList "install" -WorkingDirectory $frontendDir -Wait -PassThru -NoNewWindow -RedirectStandardOutput $npmLog -RedirectStandardError $npmErrLog
            if ($proc1.ExitCode -eq 0) {
                Write-Ok "Frontend dependencies installed"
                Write-Step "Building frontend (this may take a minute)..."
                $proc2 = Start-Process -FilePath $npmPath -ArgumentList "run build" -WorkingDirectory $frontendDir -Wait -PassThru -NoNewWindow -RedirectStandardOutput $npmLog -RedirectStandardError $npmErrLog
                if ($proc2.ExitCode -eq 0 -and (Test-Path (Join-Path (Join-Path $frontendDir "dist") "index.html"))) {
                    Write-Ok "Frontend built"
                } else {
                    # Hard fail (INF-0004 #1): a failed build means a blank/404 UI. Do not
                    # let the installer claim success -- the customer would be wedged with
                    # no way to know why.
                    Exit-WithError "Frontend build failed. See $npmLog and $npmErrLog for details, then re-run install.ps1."
                }
            } else {
                # Hard fail (INF-0004 #1): without node_modules the build cannot run.
                Exit-WithError "Frontend dependency install (npm install) failed. See $npmLog and $npmErrLog for details, then re-run install.ps1."
            }
        } else {
            Write-Warn "npm not found - startup.py will handle frontend on first run"
        }
    }
}

# ---------------------------------------------------------------------------
# Phase 4 -- Database and configuration via install.py
# ---------------------------------------------------------------------------

function Invoke-InstallPy {
    param([string]$TargetDir)

    Write-Phase "4" "Database and configuration setup"

    $venvPython = Join-Path (Join-Path (Join-Path $TargetDir "venv") "Scripts") "python.exe"
    $installPy  = Join-Path $TargetDir "install.py"

    if (-not (Test-Path $installPy)) {
        Exit-WithError "install.py not found in $TargetDir. The release may be incomplete."
    }

    Write-Step "Running install.py for database setup, config generation, and template seeding..."
    Write-Host ""

    Push-Location $TargetDir
    try {
        & $venvPython $installPy --setup-only
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            Exit-WithError "install.py exited with code $LASTEXITCODE. Check the output above for details."
        }
    } finally {
        Pop-Location
    }

    Write-Ok "Database and configuration setup complete"
}

# ---------------------------------------------------------------------------
# Phase 5 -- Shortcuts and launcher
# ---------------------------------------------------------------------------

function Install-Shortcuts {
    param([string]$TargetDir, [string]$Version)

    Write-Phase "5" "Creating shortcuts and launcher"

    # Create start-giljoai.bat
    $batPath = Join-Path $TargetDir "start-giljoai.bat"
    $batContent = @"
@echo off
title Giljo HQ Server
cd /d "%~dp0"
call venv\Scripts\activate.bat
python startup.py --verbose
pause
"@
    Set-Content -Path $batPath -Value $batContent -Encoding ASCII
    Write-Ok "Created start-giljoai.bat"

    # Resolve icon path - Start.ico ships in frontend/public/
    $iconPath = Join-Path (Join-Path (Join-Path $TargetDir "frontend") "public") "Start.ico"
    if (-not (Test-Path $iconPath)) {
        $iconPath = Join-Path (Join-Path (Join-Path $TargetDir "frontend") "public") "favicon.ico"
    }

    # Create Start Menu shortcut
    $startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $shortcutPath = Join-Path $startMenuDir "Giljo HQ.lnk"

    try {
        $wshShell = New-Object -ComObject WScript.Shell
        $shortcut = $wshShell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $batPath
        $shortcut.WorkingDirectory = $TargetDir
        $shortcut.Description = "Giljo HQ Server v$Version"
        if (Test-Path $iconPath) { $shortcut.IconLocation = "$iconPath, 0" }
        $shortcut.Save()
        Write-Ok "Start Menu shortcut created"
    } catch {
        Write-Warn "Could not create Start Menu shortcut: $_"
    }

    # Desktop shortcut
    $desktopPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Giljo HQ.lnk"
    try {
        $wshShell2 = New-Object -ComObject WScript.Shell
        $desktopShortcut = $wshShell2.CreateShortcut($desktopPath)
        $desktopShortcut.TargetPath = $batPath
        $desktopShortcut.WorkingDirectory = $TargetDir
        $desktopShortcut.Description = "Giljo HQ Server v$Version"
        if (Test-Path $iconPath) { $desktopShortcut.IconLocation = "$iconPath, 0" }
        $desktopShortcut.Save()
        Write-Ok "Desktop shortcut created"
    } catch {
        Write-Warn "Could not create desktop shortcut: $_"
    }
}

# ---------------------------------------------------------------------------
# Phase 6 -- Done
# ---------------------------------------------------------------------------

function Show-Completion {
    param([string]$TargetDir, [string]$Version)

    Write-Host ""
    Write-Host "    Installer finished. To start the server:" -ForegroundColor $script:INFO_COLOR
    Write-Host ""
    Write-Host "      cd $TargetDir" -ForegroundColor White
    Write-Host "      python startup.py --verbose" -ForegroundColor White
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Update detection
# ---------------------------------------------------------------------------

function Test-ExistingInstall {
    <#
    .SYNOPSIS
        Checks if a previous installation exists and returns its version.
        Returns $null if no existing install, or a hashtable with version info.
    #>
    param([string]$TargetDir)

    $versionFile = Join-Path $TargetDir "VERSION"
    $venvDir = Join-Path $TargetDir "venv"
    $envFile = Join-Path $TargetDir ".env"

    # Require VERSION + (venv/ OR .env). VERSION alone false-positives on
    # cloned source repos (which ship a VERSION file but have no venv/.env
    # -- those are install-time artifacts only). Without the multi-signal
    # check, running this script from inside a clone with $PWD == repo root
    # was incorrectly detected as "v1.2.x already installed."
    if ((Test-Path $versionFile) -and ((Test-Path $venvDir) -or (Test-Path $envFile))) {
        $currentVersion = (Get-Content $versionFile -Raw).Trim()
        return @{ CurrentVersion = $currentVersion }
    }
    return $null
}

function Confirm-UpdateAction {
    <#
    .SYNOPSIS
        Prompts user to choose between Update, Reinstall, or Cancel when an
        existing installation is detected.
    #>
    param([string]$CurrentVersion, [string]$LatestVersion)

    # Unattended runs have no console to answer this, so Read-Host below would
    # block forever against any non-clean target -- the automated installer lab
    # hung here rather than failing. Abort instead of guessing: "update" would
    # touch an install we were not asked to touch, and "reinstall" would destroy
    # it. The caller can state its intent explicitly with -Update, or point
    # GILJO_INSTALL_DIR at a directory that has no install in it. (INF-9321)
    if ($env:GILJO_UNATTENDED -eq "1") {
        Exit-WithError ("An existing Giljo HQ installation (version $CurrentVersion) was found in the target directory, " +
            "and GILJO_UNATTENDED=1 leaves no way to ask what to do with it. Re-run with -Update to upgrade it in " +
            "place (config and data are preserved), or set GILJO_INSTALL_DIR to an empty directory for a fresh install.")
    }

    Write-Host ""
    Write-Host "    Existing installation detected!" -ForegroundColor $script:BRAND_COLOR
    Write-Host "    Current version: $CurrentVersion" -ForegroundColor $script:INFO_COLOR
    Write-Host "    Latest version:  $LatestVersion" -ForegroundColor $script:INFO_COLOR
    Write-Host ""
    Write-Host "    [U] Update (preserves config and data)" -ForegroundColor $script:INFO_COLOR
    Write-Host "    [R] Reinstall (fresh install)" -ForegroundColor $script:INFO_COLOR
    Write-Host "    [C] Cancel" -ForegroundColor $script:MUTED_COLOR
    Write-Host ""
    Write-Host "    Choice [U/R/C]: " -ForegroundColor $script:BRAND_COLOR -NoNewline
    $choice = Read-Host

    switch ($choice.ToUpper()) {
        "U" { return "update" }
        "R" { return "reinstall" }
        default { return "cancel" }
    }
}

# ---------------------------------------------------------------------------
# Main entry point -- wrapped in a function to avoid variable leaks via iex
# ---------------------------------------------------------------------------

function Save-TranscriptToInstallLog {
    # Stop the transcript and append a redacted copy into <TargetDir>\install.log so
    # the customer ends up with ONE continuous log across Phases 1-6. The temp
    # transcript may hold raw output; the persisted copy is scrubbed. (INF-0004 #5)
    param([bool]$TranscriptStarted)
    if (-not $TranscriptStarted) { return }
    try { Stop-Transcript | Out-Null } catch { }
    if ($script:ResolvedTargetDir -and (Test-Path $script:ResolvedTargetDir) -and (Test-Path $script:TranscriptPath)) {
        try {
            $raw = Get-Content -Raw -LiteralPath $script:TranscriptPath
            $redacted = [regex]::Replace($raw, $script:SensitivePattern, '$1$2***REDACTED***')
            Add-Content -LiteralPath (Join-Path $script:ResolvedTargetDir "install.log") -Value $redacted -Encoding UTF8
        } catch {
            # Persisting the log must never itself fail the install.
        }
    }
}

function Invoke-GiljoInstaller {
    # Start the session transcript as the VERY FIRST action so even a Phase-1 crash
    # is captured to disk (the 2026-05-22 customer crash happened before any log
    # file existed). Transcription is unsupported in a few hosts -> make it optional.
    $transcriptStarted = $false
    try {
        Start-Transcript -Path $script:TranscriptPath -Force -ErrorAction Stop | Out-Null
        $transcriptStarted = $true
    } catch {
        # No transcript host support -- continue without the unified log.
    }

    try {
        Invoke-GiljoInstallerBody
    } finally {
        Save-TranscriptToInstallLog -TranscriptStarted $transcriptStarted
    }
}

function Invoke-GiljoInstallerBody {
    Write-Banner

    # Resolve install directory.
    # Unattended: honor GILJO_INSTALL_DIR so install.ps1 and install.py (which
    # reads the same env var, install.py:3483) agree on the install location.
    # Without this, install.ps1 extracts to $PWD while install.py writes
    # config.yaml to GILJO_INSTALL_DIR -> "No such file or directory". (INF-6037)
    $targetDir = if ($InstallDir) {
        [System.IO.Path]::GetFullPath($InstallDir)
    } elseif ($env:GILJO_UNATTENDED -eq "1" -and $env:GILJO_INSTALL_DIR) {
        [System.IO.Path]::GetFullPath($env:GILJO_INSTALL_DIR)
    } else {
        $script:DEFAULT_INSTALL
    }

    # Check for existing installation
    $isUpdate = $false
    if (-not $Update) {
        $existing = Test-ExistingInstall -TargetDir $targetDir
        if ($existing) {
            # Need to fetch latest version for comparison before prompting
            try {
                $releasePreview = Invoke-RestMethod -Uri $script:GITHUB_API_URL -UseBasicParsing
                $latestVersion = $releasePreview.tag_name -replace '^v', ''
            } catch {
                $latestVersion = "(could not fetch)"
            }

            $action = Confirm-UpdateAction -CurrentVersion $existing.CurrentVersion -LatestVersion $latestVersion
            switch ($action) {
                "update"    { $isUpdate = $true }
                "reinstall" { $isUpdate = $false }
                "cancel" {
                    Write-Host "    Installation cancelled." -ForegroundColor $script:MUTED_COLOR
                    return
                }
            }
        }
    } else {
        $isUpdate = $true
    }

    # Phase 1 -- Prerequisites
    if (-not $SkipPrereqs) {
        Test-Prerequisites
    } else {
        Write-Phase "1" "Checking prerequisites"
        Write-Ok "Skipped (SkipPrereqs flag)"
    }

    # Phase 2 -- Download and verify
    $release = Get-LatestRelease

    # Phase 3 subset -- install to directory
    $targetDir = Install-Release -Release $release -TargetDir $targetDir -IsUpdate $isUpdate
    # Target dir now exists -> the finally block can persist the unified log there.
    $script:ResolvedTargetDir = $targetDir

    # Phase 3 -- Environment setup
    Initialize-Environment -TargetDir $targetDir

    # Phase 4 -- Database and config
    Invoke-InstallPy -TargetDir $targetDir

    # Phase 5 -- Shortcuts
    Install-Shortcuts -TargetDir $targetDir -Version $release.Version

    # Done
    Show-Completion -TargetDir $targetDir -Version $release.Version
}

# Run the installer
Invoke-GiljoInstaller
