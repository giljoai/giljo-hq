# Giljo HQ: Installation Guide

*Last updated: 2026-04-15*

Giljo HQ, a GiljoAI product, is a self-hosted AI agent orchestration platform. This guide covers
installing the server, completing the setup wizard, and connecting your AI coding tools.

---

## Quick Install (recommended)

A single command downloads the latest release, checks for prerequisites, sets up your
database, builds the frontend, and walks you through configuration.

**Windows (PowerShell):**
```powershell
irm giljo.ai/install.ps1 | iex
```

**Linux / macOS:**
```bash
curl -fsSL giljo.ai/install.sh | bash
```

When the installer finishes, start the server:
```bash
python startup.py
```

The installer will prompt you to install Python and PostgreSQL if they are not found.
On Linux, it installs them automatically via your package manager.

---

## Manual Install

Use this if you prefer to clone the repository and run the installer yourself.

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10 or higher | 3.12+ recommended |
| PostgreSQL | 16 minimum, 18 recommended | Must be accessible via PATH or common location |
| Node.js | 22 LTS | Required for the frontend dashboard; optional for backend-only use |
| npm | Bundled with Node.js | Used to build the frontend |
| Disk space | 500 MB minimum | For dependencies and database |

**Supported platforms:** Windows, Linux, macOS.

### 1. Clone the repository

```bash
git clone https://github.com/giljoai/giljo-hq.git
cd giljo-hq
```

### 2. Run the installer

```bash
python install.py
```

The installer displays a welcome screen and then asks configuration questions before
doing any work. Use `python install.py --headless` for non-interactive (CI/CD) installs.

### 3. Choose a network mode

The installer presents these options:

1. **Localhost only** (default): The server binds to `127.0.0.1`. HTTP only.
   Single-machine use.
2. **Auto-detect (LAN)**: The server detects your LAN IP at each startup and binds
   to `0.0.0.0`. Plain HTTP, no certificates.
3. **Specific adapter**: Select a detected network interface by IP address. Static
   binding. Plain HTTP, no certificates.
4. **Custom address**: Enter an IP or domain name manually. A private-LAN IP serves
   plain HTTP; a public domain/IP (a WAN posture) installs over plain HTTP with a
   strong cleartext warning — front it with a TLS-terminating reverse proxy/tunnel,
   or add your own certificate afterward in Settings → Network.

The server runs over plain **HTTP by default** for both localhost and LAN — no
certificate step. HTTPS is an opt-in upgrade you enable later in **Settings →
Network** (bring your own certificate). On a LAN, traffic is unencrypted: this is
appropriate for a trusted home/single-room network behind a trusted router, and you
should not port-forward the server to the internet. For an untrusted/shared network
or any internet exposure, enable HTTPS.

Press Enter to accept the default (localhost only).

### 4. Set a PostgreSQL password

**Windows:** Enter the password for the `postgres` superuser that you set when you
installed PostgreSQL. The password cannot be empty.

**Linux/macOS:** The installer attempts to set a new password for the `postgres`
account via peer authentication. Choose a password and confirm it. If peer auth is
unavailable, enter your existing PostgreSQL password when prompted.

### 5. Python version check

The installer verifies that Python 3.12 or higher is running. If the check fails,
install a supported version and re-run `python install.py`.

### 6. PostgreSQL discovery

The installer checks the system PATH, then scans platform-specific common locations
(for example, `C:\Program Files\PostgreSQL\18\bin` on Windows or `/usr/bin` on Linux).
If discovery fails, you are prompted to enter the PostgreSQL `bin` directory path
manually (up to three attempts).

If PostgreSQL is not installed, the installer prints download instructions and exits.
Download PostgreSQL 18 from https://www.postgresql.org/download/ and re-run the installer.

### 7. Node.js discovery

The installer checks for `node` and `npm` in PATH. On Linux, it offers to install
Node.js 22 LTS automatically via NodeSource if neither is found. On Windows, it prints
a link to https://nodejs.org/ and continues without the frontend. Node.js is a soft
requirement; the backend API runs without it.

### 8. Install Python dependencies

The installer creates a virtual environment in `venv/` and runs `pip install` against
`requirements.txt`. Dependencies include FastAPI, SQLAlchemy, Alembic, and the MCP SDK.

### 9. Generate configuration files

Two configuration files are written before the database is touched:

- `.env`: Contains `DATABASE_URL`, `SECRET_KEY`, and environment variables derived from
  your network mode and PostgreSQL credentials.
- `config.yaml`: Contains server bind addresses, port numbers, discovered PostgreSQL
  paths, and network mode settings.

### 10. Set up the database

The installer connects to PostgreSQL and creates the `giljo_mcp` database and
application role if they do not exist. It then creates all tables via SQLAlchemy and
seeds initial data including a default admin user and setup state.

### 11. Apply database migrations

Alembic migrations run after table creation. Migrations apply constraints,
backfills, and schema changes accumulated since the baseline. On a fresh install,
migration failure is treated as a critical error. On an upgrade, the installer logs
a warning and continues so that a DBA can resolve conflicts manually.

### 12. Install frontend dependencies

`npm install` runs in the `frontend/` directory. The installer retries up to three
times with a five-minute timeout per attempt. If Node.js is absent, this step is
skipped and the frontend is unavailable.

After npm install completes, you are prompted to choose production or development
mode for the frontend build.

### 13. Configure HTTPS (optional, after install)

The installer no longer sets up certificates. To encrypt traffic, enable HTTPS in
**Settings → Network** after the server is running. GiljoAI is bring-your-own-cert:
supply a certificate trusted by your browsers and AI coding agents — a real CA, your
organisation's internal CA, or a local CA (such as mkcert) whose root certificate you
trust on each client. You can **upload** the PEM certificate + key, or **reference**
them by path on the server (for IT-managed/rotated certificates). Then flip the HTTPS
toggle and restart.

Changing the protocol (HTTP↔HTTPS) changes the server URL, so you must re-attach and
re-authenticate your AI coding tools afterwards. Node.js-based tools (Codex CLI) also need the certificate trusted in the system CA store; the Network
settings page shows the exact commands.

### 14. Open the dashboard

After installation completes, the API starts on port 7272 and the frontend on port
7274. Open your browser to the URL printed in the success summary to reach the
dashboard and run the setup wizard.

---

## Setup Wizard

After the server starts for the first time, the dashboard displays a four-step setup
wizard.

### Step 1: Choose Tools

Select the AI coding tools you plan to connect. Options: Claude Code, Codex CLI,
OpenCode, or a generic MCP client. You can select multiple tools and connect them in the same session.

### Step 2: Connect

For each selected tool, the wizard:

1. Displays the server URL (auto-detected from your browser's location). You can
   edit the hostname and port if needed.
2. Generates an API key. Click "Generate API Key" to create a key bound to your
   session.
3. Shows the configuration command to run in your terminal.

**Claude Code:**
```bash
claude mcp add --scope user --transport http giljo_hq \
  <server-url>/mcp --header "Authorization: Bearer <api-key>"
```

**Codex CLI** (requires an environment variable first):

Set the environment variable:
```bash
# Linux/macOS
export GILJO_API_KEY="<api-key>"

# Windows PowerShell
setx GILJO_API_KEY "<api-key>"
$env:GILJO_API_KEY="<api-key>"
```

Then register the server:
```bash
codex mcp add giljo_hq --url <server-url>/mcp --bearer-token-env-var GILJO_API_KEY
```

**If you enabled HTTPS: trust the certificate (one-time, Node.js tools only)**

If your server uses HTTPS, Codex CLI needs to trust the system CA store.
Run this before starting the tool:

```bash
# Linux/macOS
export NODE_OPTIONS="--use-system-ca"

# Windows PowerShell
$env:NODE_OPTIONS = "--use-system-ca"
[System.Environment]::SetEnvironmentVariable('NODE_OPTIONS', '--use-system-ca', 'User')
```

After running the configuration command, start or restart your AI coding tool. The
wizard shows a live connection status indicator. When the tool connects, the status
dot turns green.

### Step 3: Install

Ask your connected AI coding tool to run:

```
giljo_setup
```

This MCP tool downloads the slash commands and installs them in your tool's
configuration directory, and writes the Giljo HQ marker block into your project's
`CLAUDE.md` / `AGENTS.md`. The wizard shows a "Skills downloaded" checkmark when it
completes.

It does not install agents. Every agent your orchestrator starts is handed its own
profile by the server when it begins work, so there is nothing to install or refresh.
Run `giljo_setup` again whenever your skills are outdated.

For manual setup, go to Tools > Connect in the dashboard.

### Step 4: Launch

The final step shows three action cards:

- **Define Your Product:** Create a product to organize projects, tasks, and agent
  configurations.
- **Start a Project:** Create your first project to begin orchestrating AI agents.
- **Track Your Work:** Add tasks and ideas, or look up projects and tasks, using `/giljo`.

Click any card to navigate to the corresponding section, or click "Go to Home" to
go to the dashboard home page.

---

## giljo_setup Tool

`giljo_setup` is the recommended first command to run after connecting an AI coding
tool. It downloads the slash commands as a ZIP, installs them in the correct location
for your CLI tool, and writes the Giljo HQ marker block into your project file.

The tool auto-detects the platform from the MCP client name. You can also pass a
platform explicitly:

```
giljo_setup(platform="claude_code")
giljo_setup(platform="codex_cli")
```

When setup completes, the dashboard emits a `setup:bootstrap_complete` WebSocket
event and the setup wizard advances automatically.

---

## Verifying the Connection

After connecting, ask your AI coding tool to call the `health_check` tool:

```
health_check()
```

A successful response returns status and server details.

To see what project types are configured for your tenant, call:

```
discovery(category="project_types")
```

Both tools require a valid API key. If either call fails with an authentication
error, re-run the connection step in the setup wizard to generate a new key.

---

## Troubleshooting

### PostgreSQL not found

The installer scans PATH and common installation directories. If it cannot find
PostgreSQL:

1. Verify that `psql` is installed: run `psql --version` in a terminal.
2. Add the PostgreSQL `bin` directory to PATH, then re-run the installer.
3. When prompted for a custom path, enter the full path to the `bin` directory
   (for example: `/usr/lib/postgresql/18/bin`).

Download PostgreSQL 18 from https://www.postgresql.org/download/.

### Port conflict

The API uses port 7272 and the frontend uses port 7274 by default. If another
process occupies these ports:

1. Stop the conflicting process, or
2. Edit `config.yaml` to change `api_port` and `dashboard_port` before starting.

### HTTPS certificate not trusted (HTTPS mode)

If you enabled HTTPS in Settings → Network: Node.js-based tools (Codex CLI)
reject self-signed or private certificates unless the system CA store is trusted.
Set `NODE_OPTIONS="--use-system-ca"` in your shell environment before starting the
tool. The setup wizard shows the exact command for your platform.

Claude Code does not require this step because it has its own certificate handling.

### Connection refused after installation

1. Verify the API server is running: open `http://localhost:7272/health` in a browser
   (or your configured host and port).
2. Check that the correct server URL is in the MCP configuration. The URL must end
   in `/mcp`, for example `http://localhost:7272/mcp`.
3. Verify the API key is valid. Generate a new key from the setup wizard or from
   Settings > API Keys in the dashboard.
4. For LAN/WAN mode, verify that firewall rules permit inbound connections on the
   API port.

### Frontend not available

If Node.js was not found during installation, the frontend build was skipped. Install
Node.js 22 LTS from https://nodejs.org/, then run `npm install && npm run build`
inside the `frontend/` directory and restart the API server.
