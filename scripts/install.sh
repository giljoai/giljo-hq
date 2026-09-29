#!/usr/bin/env bash

# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

# Giljo HQ -- Linux/macOS One-Liner Installer
#
# Quick install:
#   curl -fsSL giljo.ai/install.sh | bash
#
# Customized install:
#   curl -fsSL giljo.ai/install.sh | bash -s -- --install-dir /opt/giljoai --yes
#
# Update existing:
#   curl -fsSL giljo.ai/install.sh | bash -s -- --update

set -euo pipefail

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
#   export GILJO_INSTALL_SOURCE="http://YOUR-GITEA-HOST:3000/api/v1/repos/OWNER/REPO"
#
# When set, BOTH the release API endpoint AND any asset/tarball URLs are
# resolved relative to GILJO_INSTALL_SOURCE.  The Gitea v1 API is a
# GitHub-compatible superset, so the same JSON parsing code works for both.
#
# INF-0004 (installer hardening) will also touch this file.  This block is
# intentionally placed at the TOP of the source-URL section so that merge
# does not collide with INF-0004's atomic-extract / unified-log additions.
# ---------------------------------------------------------------------------
GITHUB_REPO="giljoai/giljo-hq"

if [[ -n "${GILJO_INSTALL_SOURCE:-}" ]]; then
    # Override: use the caller-supplied API base (e.g. LAN Gitea)
    RELEASE_API_BASE="${GILJO_INSTALL_SOURCE%/}"
    GITHUB_API_URL="${RELEASE_API_BASE}/releases/latest"
else
    # Default: standard public GitHub API — behavior UNCHANGED for customers
    RELEASE_API_BASE="https://api.github.com/repos/${GITHUB_REPO}"
    GITHUB_API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"
fi

# Optional auth header for self-hosted Gitea / GitHub-Enterprise mirrors that
# require a login for API and asset access. Set GILJO_INSTALL_TOKEN to a token.
# No-op for the public GitHub install path (token unset), so customer behavior
# is UNCHANGED. (INF-6037)
GH_AUTH=()
if [[ -n "${GILJO_INSTALL_TOKEN:-}" ]]; then
    GH_AUTH=(-H "Authorization: token ${GILJO_INSTALL_TOKEN}")
fi

# Default to a dedicated subdir of the user's home (matches --help's documented
# ~/giljoai-mcp), NOT $PWD. A bare one-liner is run from $HOME, and using $PWD
# there both scattered venv/frontend/data across the home dir AND made the atomic
# staging dir a sibling in the root-owned parent (/home) -> permission crash. A
# home subdir is user-owned so staging-inside-target always creates. (INF-9102)
DEFAULT_INSTALL_DIR="${HOME:-$PWD}/giljoai-mcp"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12
MIN_NODE_MAJOR=20
SERVER_PORT=7272

# ---------------------------------------------------------------------------
# CLI parameters
# ---------------------------------------------------------------------------

INSTALL_DIR=""
SKIP_PREREQS=false
UPDATE_MODE=false
AUTO_YES=false

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --install-dir)
                INSTALL_DIR="$2"
                shift 2
                ;;
            --skip-prereqs)
                SKIP_PREREQS=true
                shift
                ;;
            --update)
                UPDATE_MODE=true
                shift
                ;;
            --yes|-y)
                AUTO_YES=true
                shift
                ;;
            --help|-h)
                show_usage
                exit 0
                ;;
            *)
                err "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
}

show_usage() {
    cat <<'USAGE'
Usage: install.sh [OPTIONS]

Options:
  --install-dir DIR   Installation directory (default: ~/giljoai-mcp)
  --skip-prereqs      Skip prerequisite checks and installation
  --update            Non-interactive update of existing installation
  --yes, -y           Auto-confirm all prompts
  --help, -h          Show this help message

Examples:
  curl -fsSL giljo.ai/install.sh | bash
  curl -fsSL giljo.ai/install.sh | bash -s -- --install-dir /opt/giljoai --yes
  curl -fsSL giljo.ai/install.sh | bash -s -- --update
USAGE
}

# ---------------------------------------------------------------------------
# Color and output utilities
# ---------------------------------------------------------------------------

# Detect color support
if [[ -t 1 ]] && command -v tput &>/dev/null && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
    BRAND='\033[1;33m'   # Bold yellow
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    CYAN='\033[0;36m'
    MUTED='\033[0;90m'
    NC='\033[0m'
else
    BRAND=''
    GREEN=''
    RED=''
    CYAN=''
    MUTED=''
    NC=''
fi

print_banner() {
    echo ""
    echo -e "    ${BRAND}Giljo HQ Community Edition${NC}"
    echo -e "    ${MUTED}Linux / macOS Installer${NC}"
    echo ""
}

print_phase() {
    local number="$1" title="$2"
    echo ""
    echo -e "  ${BRAND}[$number/6] $title${NC}"
    local sep_len=$(( 6 + ${#title} ))
    echo -e "  ${MUTED}$(printf '%0.s-' $(seq 1 "$sep_len"))${NC}"
}

print_step() {
    echo -e "    ${CYAN}> $*${NC}"
}

print_ok() {
    echo -e "    ${GREEN}[OK]${NC} $*"
}

print_warn() {
    echo -e "    ${BRAND}[!]${NC} $*"
}

print_fail() {
    echo -e "    ${RED}[FAIL]${NC} $*"
}

err() {
    echo -e "${RED}[error]${NC} $*" >&2
}

exit_with_error() {
    echo ""
    # Point the customer at the log FIRST so they can paste it when reporting the
    # issue, even after closing the terminal. The EXIT trap then persists a redacted
    # copy into <TargetDir>/install.log if the target dir is known. (INF-0004 #5)
    if [[ -n "${RESOLVED_TARGET_DIR:-}" && -d "${RESOLVED_TARGET_DIR}" ]]; then
        echo -e "    ${CYAN}Full log: ${RESOLVED_TARGET_DIR}/install.log${NC} -- paste this if you report the issue"
    elif [[ -n "${INSTALL_LOG_TMP:-}" ]]; then
        echo -e "    ${CYAN}Full log: ${INSTALL_LOG_TMP}${NC} -- paste this if you report the issue"
    fi
    print_fail "$*"
    echo ""
    exit 1
}

HAS_TTY=false
TTY_FD=""
if [[ -t 0 ]]; then
    HAS_TTY=true
elif [[ -c /dev/tty ]]; then
    # Try to open /dev/tty on fd 3 for interactive reads
    if exec 3</dev/tty 2>/dev/null; then
        HAS_TTY=true
        TTY_FD=3
    fi
fi

read_input() {
    if [[ "$HAS_TTY" == true ]]; then
        if [[ -t 0 ]]; then
            read -r "$@"
        elif [[ -n "$TTY_FD" ]]; then
            read -r "$@" <&${TTY_FD}
        fi
        return 0
    fi
    return 1
}

confirm() {
    local prompt="$1"
    if [[ "$AUTO_YES" == true ]]; then
        return 0
    fi
    if [[ "$HAS_TTY" != true ]]; then
        return 0
    fi
    echo -en "    ${CYAN}$prompt [Y/n]: ${NC}"
    local answer
    read_input answer
    case "$answer" in
        n|N|no|No|NO) return 1 ;;
        *) return 0 ;;
    esac
}

# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------

OS_TYPE=""
DISTRO=""
PKG_MANAGER=""

detect_os() {
    local uname_s
    uname_s="$(uname -s)"
    case "$uname_s" in
        Linux)
            OS_TYPE="linux"
            if [[ -f /etc/os-release ]]; then
                # shellcheck source=/dev/null
                . /etc/os-release
                DISTRO="$ID"
            elif [[ -f /etc/redhat-release ]]; then
                DISTRO="rhel"
            else
                DISTRO="unknown"
            fi
            # Detect package manager
            if command -v apt-get &>/dev/null; then
                PKG_MANAGER="apt"
            elif command -v dnf &>/dev/null; then
                PKG_MANAGER="dnf"
            elif command -v yum &>/dev/null; then
                PKG_MANAGER="yum"
            fi
            ;;
        Darwin)
            OS_TYPE="macos"
            DISTRO="macos"
            if command -v brew &>/dev/null; then
                PKG_MANAGER="brew"
            fi
            ;;
        *)
            exit_with_error "Unsupported operating system: $uname_s. This installer supports Linux and macOS."
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------

parse_version() {
    # Extracts major.minor from a version string like "Python 3.12.4" or "v20.11.0"
    local version_string="$1"
    echo "$version_string" | grep -oE '[0-9]+\.[0-9]+' | head -1
}

version_major() {
    echo "$1" | cut -d. -f1
}

version_minor() {
    echo "$1" | cut -d. -f2
}

# ---------------------------------------------------------------------------
# Phase 1 -- Prerequisites
# ---------------------------------------------------------------------------

# Treat a prerequisite as satisfied ONLY when its command resolves to a REAL
# Linux binary. Under WSL, Windows drives are mounted at /mnt/<drive> and their
# executables land on PATH, so `command -v npm` can resolve to a Windows Node
# install seen through WSL even with no Linux Node present. Accepting that would
# make the installer skip the real Linux package and then fail later invoking
# the binary. Reject any resolution under /mnt/<single-letter>/ (the WSL DrvFs
# Windows-drive convention); a genuine Linux path (/usr/bin, /usr/local/bin, a
# Homebrew-on-Linux prefix, etc.) passes. Returns 0 for a real Linux binary,
# 1 if absent or a Windows/WSL binary. (INF-9106)
is_real_linux_bin() {
    local cmd="$1"
    local resolved
    resolved="$(command -v "$cmd" 2>/dev/null)" || return 1
    case "$resolved" in
        /mnt/[a-zA-Z]/*) return 1 ;;
        *) return 0 ;;
    esac
}

check_prerequisites() {
    print_phase "1" "Checking prerequisites"

    local missing=()

    # -- Python --
    print_step "Checking Python..."
    if is_real_linux_bin python3; then
        local py_raw py_ver py_major py_minor
        py_raw="$(python3 --version 2>&1)"
        py_ver="$(parse_version "$py_raw")"
        py_major="$(version_major "$py_ver")"
        py_minor="$(version_minor "$py_ver")"
        if [[ "$py_major" -gt "$MIN_PYTHON_MAJOR" ]] || \
           { [[ "$py_major" -eq "$MIN_PYTHON_MAJOR" ]] && [[ "$py_minor" -ge "$MIN_PYTHON_MINOR" ]]; }; then
            # Debian/Ubuntu/WSL ship python3 without the venv stdlib module
            # (it lives in a separate python3.X-venv apt package). The real
            # missing piece is ensurepip -- `python3 -m venv --help` returns
            # 0 even without it (help text doesn't import ensurepip), so we
            # must probe the import directly. Without this, install.sh
            # passes the prereq check, then crashes at venv-creation time
            # with "ensurepip is not available".
            if python3 -c "import ensurepip" &>/dev/null; then
                print_ok "Python ${py_major}.${py_minor} found"
            else
                print_warn "Python ${py_major}.${py_minor} found but ensurepip missing (need python3-venv apt package)"
                missing+=("python")
            fi
        else
            print_warn "Python found but version too old: $py_raw (need ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+)"
            missing+=("python")
        fi
    else
        print_warn "Python not found"
        missing+=("python")
    fi

    # -- Node.js --
    print_step "Checking Node.js..."
    if is_real_linux_bin node; then
        local node_raw node_ver node_major
        node_raw="$(node --version 2>&1)"
        node_ver="$(parse_version "$node_raw")"
        node_major="$(version_major "$node_ver")"
        if [[ "$node_major" -ge "$MIN_NODE_MAJOR" ]]; then
            print_ok "Node.js ${node_ver} found"
        else
            print_warn "Node.js found but version too old: $node_raw (need ${MIN_NODE_MAJOR}+)"
            missing+=("node")
        fi
    else
        print_warn "Node.js not found"
        missing+=("node")
    fi

    # -- Git --
    print_step "Checking Git..."
    if is_real_linux_bin git; then
        local git_raw
        git_raw="$(git --version 2>&1)"
        print_ok "Git found: $git_raw"
    else
        print_warn "Git not found"
        missing+=("git")
    fi

    # -- PostgreSQL --
    print_step "Checking PostgreSQL..."
    if is_real_linux_bin pg_isready || is_real_linux_bin psql; then
        local pg_info=""
        if is_real_linux_bin psql; then
            pg_info="$(psql --version 2>&1)"
        fi
        print_ok "PostgreSQL found${pg_info:+: $pg_info}"
    else
        print_warn "PostgreSQL not detected"
        missing+=("postgresql")
    fi

    if [[ ${#missing[@]} -eq 0 ]]; then
        print_ok "All prerequisites satisfied"
        return
    fi

    # -- Install missing prerequisites --
    echo ""
    print_step "Missing prerequisites: ${missing[*]}"

    if ! confirm "Install missing prerequisites?"; then
        exit_with_error "Cannot continue without: ${missing[*]}. Please install them manually and re-run."
    fi

    echo ""
    echo -e "    ${BRAND}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "    ${BRAND}║  Installing prerequisites (Python, Node.js, PostgreSQL)  ║${NC}"
    echo -e "    ${BRAND}║  This may take 3-5 minutes. Please do not close          ║${NC}"
    echo -e "    ${BRAND}║  this terminal.                                          ║${NC}"
    echo -e "    ${BRAND}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    install_prerequisites "${missing[@]}"

    # Final verification
    local still_missing=()
    for item in "${missing[@]}"; do
        case "$item" in
            python)    is_real_linux_bin python3 || still_missing+=("python") ;;
            node)      is_real_linux_bin node || still_missing+=("node") ;;
            git)       is_real_linux_bin git || still_missing+=("git") ;;
            postgresql) { is_real_linux_bin pg_isready || is_real_linux_bin psql; } || still_missing+=("postgresql") ;;
        esac
    done

    if [[ ${#still_missing[@]} -gt 0 ]]; then
        exit_with_error "Failed to install: ${still_missing[*]}. Please install manually and re-run."
    fi

    print_ok "All prerequisites satisfied after installation"
}

install_prerequisites() {
    local items=("$@")

    case "$OS_TYPE" in
        linux)
            install_prereqs_linux "${items[@]}"
            ;;
        macos)
            install_prereqs_macos "${items[@]}"
            ;;
    esac
}

install_prereqs_linux() {
    local items=("$@")

    # UX: the package installs below run quietly (apt/dnf -q) and can take a
    # minute or two with little output. Set expectations and prime sudo up front
    # so the password prompt appears HERE (not mid-silence) and the user knows to
    # wait instead of thinking the installer hung.
    print_step "Installing system packages needs administrator (sudo) access."
    print_step "You'll be asked for your password once; after that it runs quietly for a minute or two — please wait..."
    sudo -v || true

    case "$PKG_MANAGER" in
        apt)
            # Use Cloudflare's Ubuntu mirror for faster package downloads
            # Save original sources, swap in Cloudflare mirror, restore after install
            local sources_file="/etc/apt/sources.list"
            local sources_dir="/etc/apt/sources.list.d"
            local backup_sources=""
            if [[ -f "$sources_file" ]] && grep -q "archive.ubuntu.com\|security.ubuntu.com" "$sources_file" 2>/dev/null; then
                backup_sources="$(cat "$sources_file")"
                sudo sed -i 's|http://archive.ubuntu.com/ubuntu|http://us.archive.ubuntu.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|http://us.archive.ubuntu.com/ubuntu|g' "$sources_file" </dev/null
                print_step "Updating package lists (via US mirror)..."
            else
                print_step "Updating package lists..."
            fi
            sudo apt-get -o DPkg::Lock::Timeout=300 update -qq </dev/null

            for item in "${items[@]}"; do
                case "$item" in
                    python)
                        print_step "Installing Python 3.12..."
                        if apt-cache show python3.12 &>/dev/null; then
                            sudo apt-get -o DPkg::Lock::Timeout=300 install -y -qq python3.12 python3.12-venv python3-pip </dev/null
                        else
                            print_step "Adding deadsnakes PPA for Python 3.12..."
                            sudo add-apt-repository -y ppa:deadsnakes/ppa </dev/null
                            sudo apt-get -o DPkg::Lock::Timeout=300 update -qq </dev/null
                            sudo apt-get -o DPkg::Lock::Timeout=300 install -y -qq python3.12 python3.12-venv python3-pip </dev/null
                        fi
                        print_ok "Python installed"
                        ;;
                    node)
                        print_step "Installing Node.js 22..."
                        # Direct binary from nodejs.org CDN — fast, no repo setup needed
                        local node_ver="v22.22.0"
                        local node_arch="x64"
                        [[ "$(uname -m)" == "aarch64" ]] && node_arch="arm64"
                        curl -fsSL "https://nodejs.org/dist/${node_ver}/node-${node_ver}-linux-${node_arch}.tar.xz" | sudo tar -xJ -C /usr/local --strip-components=1
                        print_ok "Node.js installed"
                        ;;
                    git)
                        print_step "Installing Git..."
                        sudo apt-get -o DPkg::Lock::Timeout=300 install -y -qq git </dev/null
                        print_ok "Git installed"
                        ;;
                    postgresql)
                        print_step "Installing PostgreSQL 18..."
                        sudo rm -f /etc/apt/sources.list.d/pgdg.list /etc/apt/sources.list.d/pgdg.sources </dev/null
                        sudo sh -c 'echo "deb https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
                        curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor --yes -o /etc/apt/trusted.gpg.d/pgdg.gpg
                        sudo apt-get -o DPkg::Lock::Timeout=300 update -qq </dev/null
                        sudo apt-get -o DPkg::Lock::Timeout=300 install -y -qq postgresql-18 postgresql-client-18 </dev/null
                        sudo systemctl start postgresql </dev/null
                        sudo systemctl enable postgresql </dev/null
                        print_ok "PostgreSQL installed and started"
                        ;;
                esac
            done

            # Restore original apt sources if we swapped to Cloudflare
            if [[ -n "$backup_sources" ]]; then
                echo "$backup_sources" | sudo tee "$sources_file" >/dev/null
                print_step "Restored original apt sources"
            fi
            ;;
        dnf|yum)
            for item in "${items[@]}"; do
                case "$item" in
                    python)
                        print_step "Installing Python 3.12..."
                        sudo "$PKG_MANAGER" install -y python3.12 python3-pip python3-devel </dev/null 2>/dev/null || \
                            sudo "$PKG_MANAGER" install -y python3 python3-pip python3-devel </dev/null
                        print_ok "Python installed"
                        ;;
                    node)
                        print_step "Installing Node.js 22..."
                        curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash - </dev/null
                        sudo "$PKG_MANAGER" install -y nodejs </dev/null
                        print_ok "Node.js installed"
                        ;;
                    git)
                        print_step "Installing Git..."
                        sudo "$PKG_MANAGER" install -y git </dev/null
                        print_ok "Git installed"
                        ;;
                    postgresql)
                        print_step "Installing PostgreSQL..."
                        sudo "$PKG_MANAGER" install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm </dev/null 2>/dev/null || true
                        sudo "$PKG_MANAGER" install -y postgresql-server postgresql </dev/null
                        sudo postgresql-setup --initdb </dev/null 2>/dev/null || true
                        sudo systemctl start postgresql </dev/null
                        sudo systemctl enable postgresql </dev/null
                        print_ok "PostgreSQL installed and started"
                        ;;
                esac
            done
            ;;
        *)
            exit_with_error "No supported package manager found (apt/dnf/yum). Please install manually: ${items[*]}"
            ;;
    esac
}

install_prereqs_macos() {
    local items=("$@")

    # Ensure Homebrew is available
    if ! command -v brew &>/dev/null; then
        print_step "Homebrew not found. Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Add brew to PATH for Apple Silicon
        if [[ -f "/opt/homebrew/bin/brew" ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
    fi

    for item in "${items[@]}"; do
        case "$item" in
            python)
                print_step "Installing Python 3.12..."
                brew install python@3.12
                print_ok "Python installed"
                ;;
            node)
                print_step "Installing Node.js..."
                brew install node
                print_ok "Node.js installed"
                ;;
            git)
                print_step "Installing Git..."
                brew install git
                print_ok "Git installed"
                ;;
            postgresql)
                print_step "Installing PostgreSQL..."
                brew install postgresql@18
                brew services start postgresql@18
                print_ok "PostgreSQL installed and started"
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Phase 2 -- Download and verify
# ---------------------------------------------------------------------------

RELEASE_VERSION=""
RELEASE_TARBALL=""
TEMP_DIR=""

# Unified install log (INF-0004 sub-task #5). main() tees the WHOLE Phase-1..6
# session into INSTALL_LOG_TMP from the start, so a Phase-1 crash (before install.py's
# own install.log exists) is still diagnosable after the terminal closes. On EXIT a
# redacted copy is appended into <TargetDir>/install.log once the target is known.
INSTALL_LOG_TMP=""
RESOLVED_TARGET_DIR=""

persist_install_log() {
    [[ -n "$INSTALL_LOG_TMP" && -f "$INSTALL_LOG_TMP" ]] || return 0
    [[ -n "$RESOLVED_TARGET_DIR" && -d "$RESOLVED_TARGET_DIR" ]] || return 0
    # Redact credential-looking tokens before persisting (mirrors install.py's
    # _SENSITIVE_PATTERNS so both halves of the unified log scrub the same shapes).
    # LC_ALL=C keeps BSD sed from rejecting non-UTF-8 bytes; if redaction still
    # fails, only a marker is written, never the raw log.
    if ! LC_ALL=C sed -E 's/([Pp]assword|[Pp]asswd|[Ss]ecret|[Tt]oken|[Kk]ey|[Cc]redential)([=:[:space:]]+)[^[:space:]]+/\1\2***REDACTED***/g' \
        "$INSTALL_LOG_TMP" >> "${RESOLVED_TARGET_DIR}/install.log" 2>/dev/null; then
        echo "install log redaction failed; raw log not persisted" >> "${RESOLVED_TARGET_DIR}/install.log" 2>/dev/null || true
    fi
    rm -f "$INSTALL_LOG_TMP"
}

cleanup() {
    persist_install_log
    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT

download_release() {
    print_phase "2" "Downloading latest release"

    TEMP_DIR="$(mktemp -d)"

    # Fetch release metadata
    print_step "Fetching latest release info from GitHub..."
    local release_json
    release_json="$(curl -fsSL "${GH_AUTH[@]}" "$GITHUB_API_URL")" || \
        exit_with_error "Failed to fetch release info from GitHub. Check your internet connection."

    # Parse version and manifest URL using python3 (avoids jq dependency)
    RELEASE_VERSION="$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(data['tag_name'].lstrip('v'))
" <<< "$release_json")"
    print_ok "Latest version: $RELEASE_VERSION"

    # Find version-manifest.json asset URL
    local manifest_url
    manifest_url="$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
assets = data.get('assets', [])
for a in assets:
    if a['name'] == 'version-manifest.json':
        print(a['browser_download_url'])
        sys.exit(0)
print('')
" <<< "$release_json")"

    if [[ -z "$manifest_url" ]]; then
        exit_with_error "Release is missing version-manifest.json. This release may be malformed."
    fi

    # Download and parse the manifest
    print_step "Downloading version manifest..."
    local manifest_json
    manifest_json="$(curl -fsSL "${GH_AUTH[@]}" "$manifest_url")" || \
        exit_with_error "Failed to download version manifest."

    local tarball_url expected_sha
    tarball_url="$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['tarball_url'])" <<< "$manifest_json")"
    expected_sha="$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d['sha256'])" <<< "$manifest_json")"

    if [[ -z "$tarball_url" || -z "$expected_sha" ]]; then
        exit_with_error "Version manifest is incomplete (missing tarball_url or sha256)."
    fi

    # Download tarball
    local tarball_name="giljo-hq-${RELEASE_VERSION}.tar.gz"
    RELEASE_TARBALL="${TEMP_DIR}/${tarball_name}"

    print_step "Downloading $tarball_name..."
    curl -fsSL "${GH_AUTH[@]}" -o "$RELEASE_TARBALL" "$tarball_url" || \
        exit_with_error "Failed to download tarball from $tarball_url"
    print_ok "Downloaded to $RELEASE_TARBALL"

    # Verify SHA256
    print_step "Verifying SHA256 checksum..."
    local actual_sha
    if command -v sha256sum &>/dev/null; then
        actual_sha="$(sha256sum "$RELEASE_TARBALL" | awk '{print $1}')"
    elif command -v shasum &>/dev/null; then
        actual_sha="$(shasum -a 256 "$RELEASE_TARBALL" | awk '{print $1}')"
    else
        exit_with_error "Neither sha256sum nor shasum found. Cannot verify download integrity."
    fi

    # Normalize to lowercase for comparison
    actual_sha="$(echo "$actual_sha" | tr '[:upper:]' '[:lower:]')"
    expected_sha="$(echo "$expected_sha" | tr '[:upper:]' '[:lower:]')"

    if [[ "$actual_sha" != "$expected_sha" ]]; then
        rm -f "$RELEASE_TARBALL"
        exit_with_error "SHA256 mismatch! Expected: $expected_sha, Got: $actual_sha. The download may be corrupted or tampered with."
    fi
    print_ok "SHA256 verified: $actual_sha"
}

# ---------------------------------------------------------------------------
# Install / extract
# ---------------------------------------------------------------------------

install_release() {
    local target_dir="$1"
    local is_update="$2"
    local backup_dir=""

    # Back up config files before extraction if updating
    if [[ "$is_update" == true ]]; then
        print_step "Backing up configuration files..."
        backup_dir="${TEMP_DIR}/config-backup"
        mkdir -p "$backup_dir"
        for f in .env config.yaml; do
            if [[ -f "${target_dir}/$f" ]]; then
                cp "${target_dir}/$f" "${backup_dir}/$f"
                print_ok "Backed up $f"
            fi
        done
    fi

    # Atomic extraction (INF-0004 sub-task #2): extract into a staging dir that is a
    # hidden CHILD of target_dir (NOT a sibling), so the final per-entry moves are
    # same-filesystem renames, which are atomic. A Ctrl+C / power-loss DURING the slow
    # extract only litters the staging child -- the live install is left untouched, and
    # a re-run cleans the stale staging dir. Install-time artifacts (venv/, .env,
    # config.yaml, data/, logs/) are NOT in the tarball, so the per-entry swap
    # replaces only release files and leaves user data intact.
    #
    # Why a child and not a sibling "${target_dir}.new": the default install dir is a
    # subdir of $HOME, whose parent (/home) is root-owned -- an unprivileged user
    # cannot create a sibling there ("mkdir: .new: Permission denied"). target_dir is
    # already created and user-owned, so a child always creates and stays same-fs
    # (preserves INF-0004's atomic-rename guarantee -- do NOT stage in /tmp). (INF-9102)
    if ! mkdir -p "$target_dir" 2>/dev/null; then
        exit_with_error "Cannot create install directory: ${target_dir} -- check write permissions for its parent."
    fi
    local staging_dir="${target_dir}/.giljo-staging-$$"
    rm -rf "$staging_dir"
    # Preflight: prove the staging child is creatable in the chosen target BEFORE the
    # slow download-extract, so a bad target fails early with a clear, named message.
    if ! mkdir -p "$staging_dir" 2>/dev/null; then
        exit_with_error "Cannot create staging directory inside ${target_dir} -- check write permissions for that path."
    fi

    print_step "Extracting release to a staging area..."
    if ! tar -xzf "$RELEASE_TARBALL" -C "$staging_dir" --strip-components=1; then
        rm -rf "$staging_dir"
        exit_with_error "Failed to extract release archive. Re-run the installer to try again."
    fi

    print_step "Installing release files..."
    # dotglob: include hidden files (.env.example etc.); nullglob: empty dir -> no
    # literal '*' iteration. Restore both afterwards regardless of outcome.
    # `shopt -p <name>` prints the restore command but EXITS 1 when the option is
    # unset -- and dotglob/nullglob are off by default in a `curl | bash` shell.
    # Under `set -euo pipefail` that non-zero status killed the whole installer
    # right here (silently) before any file was moved into place. `|| true` keeps
    # the captured restore command while neutralising the errexit trap. (INF-9106)
    local _had_dotglob _had_nullglob
    _had_dotglob="$(shopt -p dotglob || true)"; _had_nullglob="$(shopt -p nullglob || true)"
    shopt -s dotglob nullglob
    local entry name
    for entry in "$staging_dir"/*; do
        name="$(basename "$entry")"
        rm -rf "${target_dir:?}/${name}"
        mv "$entry" "${target_dir}/${name}"
    done
    eval "$_had_dotglob"; eval "$_had_nullglob"
    rm -rf "$staging_dir"
    print_ok "Extraction complete"

    # Restore backed-up config files
    if [[ "$is_update" == true && -n "$backup_dir" ]]; then
        print_step "Restoring configuration files..."
        for f in .env config.yaml; do
            if [[ -f "${backup_dir}/$f" ]]; then
                cp "${backup_dir}/$f" "${target_dir}/$f"
                print_ok "Restored $f"
            fi
        done
    fi

    # Write VERSION file
    echo -n "$RELEASE_VERSION" > "${target_dir}/VERSION"
}

# ---------------------------------------------------------------------------
# Phase 3 -- Environment setup
# ---------------------------------------------------------------------------

setup_environment() {
    local target_dir="$1"
    print_phase "3" "Setting up environment"

    local venv_dir="${target_dir}/venv"
    local venv_python="${venv_dir}/bin/python"
    local venv_pip="${venv_dir}/bin/pip"

    # Create venv if it does not exist
    if [[ ! -f "$venv_python" ]]; then
        print_step "Creating Python virtual environment..."
        python3 -m venv "$venv_dir"
        print_ok "Virtual environment created"
    else
        print_ok "Virtual environment already exists"
    fi

    # Upgrade pip. Let it stream (no --quiet / 2>/dev/null) so the user sees progress;
    # --timeout 60 bounds each connection. (INF-0004 #4)
    print_step "Upgrading pip..."
    "$venv_python" -m pip install --upgrade pip --timeout 60
    print_ok "pip upgraded"

    # Install Python dependencies. Previously `--quiet 2>/dev/null` hid BOTH the
    # 2-3 min progress AND wheel-compile errors (missing libpq-dev / gcc), and had
    # NO timeout (a slow PyPI mirror wedged forever). Now: visible, fails loudly,
    # bounded by `timeout 600` overall + `--timeout 60` per connection. (INF-0004 #1/#4)
    local requirements="${target_dir}/requirements.txt"
    # INF-9057: requirements.lock ships with the release and pins the full
    # resolved dependency tree. Passed as a pip CONSTRAINTS file (-c) it pins
    # every package pip installs (platform-inapplicable entries are ignored),
    # so a breaking upstream release cannot break a fresh install. Its absence
    # (an older extracted release) is tolerated -- pip resolves the floors.
    # The ${arr[@]+...} expansion keeps the empty-array case safe under set -u
    # on bash <4.4 (macOS ships bash 3.2).
    local constraints="${target_dir}/requirements.lock"
    local constraint_args=()
    if [[ -f "$constraints" ]]; then
        constraint_args=(-c "$constraints")
    fi
    if [[ -f "$requirements" ]]; then
        print_step "Installing Python dependencies (this may take a few minutes)..."
        if ! timeout 600 "$venv_pip" install -r "$requirements" ${constraint_args[@]+"${constraint_args[@]}"} --timeout 60; then
            exit_with_error "Installing Python dependencies failed (see the output above). On Linux this is often a missing system library such as libpq-dev or gcc -- install it, then re-run the installer."
        fi
        print_ok "Python dependencies installed"
    else
        print_warn "requirements.txt not found -- skipping pip install"
    fi

    # Register giljo_mcp as importable package (editable install, idempotent).
    # Best-effort (non-fatal), but now visible rather than black-holed.
    if [[ -f "${target_dir}/pyproject.toml" ]]; then
        if timeout 600 "$venv_pip" install -e "$target_dir" ${constraint_args[@]+"${constraint_args[@]}"} --timeout 60; then
            print_ok "Package registered (editable install)"
        else
            print_warn "Editable install skipped (non-fatal)"
        fi
    fi

    # Build frontend. Hard fail on npm install/build failure (INF-0004 #1) -- a blank
    # /404 UI must not be reported as a successful install -- and let npm stream so
    # the failure cause is visible (INF-0004 #4: was `> /dev/null 2>&1`).
    local frontend_dir="${target_dir}/frontend"
    if [[ -f "${frontend_dir}/package.json" ]]; then
        print_step "Installing frontend dependencies..."
        if ! (cd "$frontend_dir" && npm install); then
            exit_with_error "Frontend dependency install (npm install) failed (see the output above). Re-run the installer to try again."
        fi
        print_ok "Frontend dependencies installed"

        print_step "Building frontend (this may take a minute)..."
        if ! (cd "$frontend_dir" && npm run build); then
            exit_with_error "Frontend build failed (see the output above). Re-run the installer to try again."
        fi
        if [[ ! -f "${frontend_dir}/dist/index.html" ]]; then
            exit_with_error "Frontend build did not produce dist/index.html. Re-run the installer to try again."
        fi
        print_ok "Frontend built"
    else
        print_warn "Frontend package.json not found -- skipping frontend build"
    fi
}

# ---------------------------------------------------------------------------
# Phase 4 -- Database and configuration via install.py
# ---------------------------------------------------------------------------

run_install_py() {
    local target_dir="$1"
    print_phase "4" "Database and configuration setup"

    local venv_python="${target_dir}/venv/bin/python"
    local install_py="${target_dir}/install.py"

    if [[ ! -f "$install_py" ]]; then
        exit_with_error "install.py not found in $target_dir. The release may be incomplete."
    fi

    print_step "Running install.py for database setup, config generation, and template seeding..."
    echo ""

    # Redirect TTY into install.py so interactive prompts work
    # even when the bash script itself was piped via curl | bash
    if [[ -n "$TTY_FD" ]]; then
        (cd "$target_dir" && "$venv_python" "$install_py" --setup-only <&${TTY_FD}) || \
            exit_with_error "install.py failed. Check the output above for details."
    else
        (cd "$target_dir" && "$venv_python" "$install_py" --setup-only) || \
            exit_with_error "install.py failed. Check the output above for details."
    fi

    print_ok "Database and configuration setup complete"
}

# ---------------------------------------------------------------------------
# Phase 5 -- Service setup
# ---------------------------------------------------------------------------

save_service_files() {
    local target_dir="$1"
    print_phase "5" "Service files"

    local current_user
    current_user="$(whoami)"

    case "$OS_TYPE" in
        linux)
            cat > "${target_dir}/giljoai-mcp.service" <<UNIT
[Unit]
Description=Giljo HQ Server
After=network.target postgresql.service

[Service]
Type=simple
User=${current_user}
WorkingDirectory=${target_dir}
ExecStart=${target_dir}/venv/bin/python ${target_dir}/startup.py
Restart=on-failure
RestartSec=5
Environment=PATH=${target_dir}/venv/bin:/usr/local/bin:/usr/bin

[Install]
WantedBy=multi-user.target
UNIT
            print_ok "Saved giljoai-mcp.service (optional — for running as a background service)"
            ;;
        macos)
            cat > "${target_dir}/com.giljoai.mcp.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.giljoai.mcp</string>
    <key>ProgramArguments</key>
    <array>
        <string>${target_dir}/venv/bin/python</string>
        <string>${target_dir}/startup.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${target_dir}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${target_dir}/logs/server.log</string>
    <key>StandardErrorPath</key>
    <string>${target_dir}/logs/server.err</string>
</dict>
</plist>
PLIST
            print_ok "Saved com.giljoai.mcp.plist (optional — for running as a background service)"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Phase 6 -- First run
# ---------------------------------------------------------------------------

first_run() {
    local target_dir="$1"
    local version="$2"

    echo ""
    echo -e "    ${CYAN}Installer finished. To start the server:${NC}"
    echo ""
    echo -e "    ${NC}  cd $target_dir${NC}"
    echo -e "    ${NC}  python3 startup.py --verbose${NC}"
    echo ""
}

# ---------------------------------------------------------------------------
# Update detection
# ---------------------------------------------------------------------------

check_existing_install() {
    local target_dir="$1"
    local version_file="${target_dir}/VERSION"
    local venv_dir="${target_dir}/venv"
    local env_file="${target_dir}/.env"

    # Require VERSION + (venv/ OR .env). VERSION alone false-positives on
    # cloned source repos (which ship a VERSION file but have no venv/.env
    # -- those are install-time artifacts only). Without the multi-signal
    # check, running this script from inside a clone with $PWD == repo root
    # was incorrectly detected as "v1.2.x already installed."
    if [[ -f "$version_file" ]] && { [[ -d "$venv_dir" ]] || [[ -f "$env_file" ]]; }; then
        cat "$version_file"
        return 0
    fi
    return 1
}

stop_existing_service() {
    local target_dir="$1"
    print_step "Stopping existing service..."

    case "$OS_TYPE" in
        linux)
            if systemctl is-active giljoai-mcp &>/dev/null; then
                sudo systemctl stop giljoai-mcp </dev/null
                print_ok "systemd service stopped"
            fi
            ;;
        macos)
            local plist="$HOME/Library/LaunchAgents/com.giljoai.mcp.plist"
            if [[ -f "$plist" ]]; then
                launchctl unload "$plist" 2>/dev/null || true
                print_ok "launchd agent unloaded"
            fi
            ;;
    esac
}

restart_service() {
    local target_dir="$1"
    print_step "Restarting service..."

    case "$OS_TYPE" in
        linux)
            if systemctl is-enabled giljoai-mcp &>/dev/null; then
                sudo systemctl restart giljoai-mcp </dev/null
                print_ok "systemd service restarted"
            fi
            ;;
        macos)
            local plist="$HOME/Library/LaunchAgents/com.giljoai.mcp.plist"
            if [[ -f "$plist" ]]; then
                launchctl unload "$plist" 2>/dev/null || true
                launchctl load "$plist"
                print_ok "launchd agent restarted"
            fi
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

main() {
    parse_args "$@"

    # Tee the whole session to a temp log from the very first output (INF-0004 #5).
    # mktemp is preferred; fall back to a PID-named file if mktemp is unavailable.
    INSTALL_LOG_TMP="$(mktemp 2>/dev/null || echo "/tmp/giljoai-install.$$.log")"
    exec > >(tee -a "$INSTALL_LOG_TMP") 2>&1

    print_banner
    detect_os

    print_step "Detected OS: ${OS_TYPE} (${DISTRO})"
    if [[ -n "$PKG_MANAGER" ]]; then
        print_step "Package manager: ${PKG_MANAGER}"
    fi

    # Resolve install directory
    local target_dir
    if [[ -n "$INSTALL_DIR" ]]; then
        target_dir="$INSTALL_DIR"
    else
        target_dir="$DEFAULT_INSTALL_DIR"
    fi
    # Resolve to absolute path
    target_dir="$(cd "$(dirname "$target_dir")" 2>/dev/null && pwd)/$(basename "$target_dir")" 2>/dev/null || target_dir="$target_dir"

    # Check for existing installation
    local is_update=false
    if [[ "$UPDATE_MODE" == true ]]; then
        is_update=true
    else
        local current_version=""
        if current_version="$(check_existing_install "$target_dir")"; then
            echo ""
            echo -e "    ${BRAND}Existing installation detected!${NC}"
            echo -e "    ${CYAN}Current version: ${current_version}${NC}"
            echo ""
            if [[ "$AUTO_YES" == true ]]; then
                is_update=true
            else
                echo -e "    ${CYAN}[U] Update (preserves config and data)${NC}"
                echo -e "    ${CYAN}[R] Reinstall (fresh install)${NC}"
                echo -e "    ${MUTED}[C] Cancel${NC}"
                echo ""
                echo -en "    ${BRAND}Choice [U/R/C]: ${NC}"
                if ! read_input choice; then
                    choice="U"
                fi
                case "${choice^^}" in
                    U) is_update=true ;;
                    R) is_update=false ;;
                    *)
                        echo -e "    ${MUTED}Installation cancelled.${NC}"
                        exit 0
                        ;;
                esac
            fi
        else
            # No existing install and not a custom dir -- ask for directory
            if [[ -z "$INSTALL_DIR" && "$AUTO_YES" != true ]]; then
                echo ""
                echo -en "    ${CYAN}Install directory [$target_dir]: ${NC}"
                if ! read_input user_dir; then
                    user_dir=""
                fi
                if [[ -n "$user_dir" ]]; then
                    target_dir="$user_dir"
                fi
            fi
        fi
    fi

    # Phase 1 -- Prerequisites
    if [[ "$SKIP_PREREQS" == true ]]; then
        print_phase "1" "Checking prerequisites"
        print_ok "Skipped (--skip-prereqs flag)"
    else
        check_prerequisites
    fi

    # Phase 2 -- Download and verify
    download_release

    # Stop existing service if updating
    if [[ "$is_update" == true ]]; then
        stop_existing_service "$target_dir"
    fi

    # Extract release
    install_release "$target_dir" "$is_update"
    # Target dir now exists -> the EXIT trap can persist the unified log there.
    RESOLVED_TARGET_DIR="$target_dir"

    # Phase 3 -- Environment setup
    setup_environment "$target_dir"

    # Phase 4 -- Database and config via install.py
    run_install_py "$target_dir"

    # Phase 5 -- Service files + migrations (if updating)
    if [[ "$is_update" == true ]]; then
        print_phase "5" "Database migrations"
        local venv_python="${target_dir}/venv/bin/python"
        if [[ -f "${target_dir}/alembic.ini" ]]; then
            print_step "Running database migrations..."
            (cd "$target_dir" && "$venv_python" -m alembic upgrade head 2>&1) || \
                print_warn "Alembic migration failed -- may need manual intervention"
        fi
        print_ok "Update applied — restart the server to use the new version"
    else
        save_service_files "$target_dir"
    fi

    # Phase 6 -- First run
    first_run "$target_dir" "$RELEASE_VERSION"
}

main "$@"
