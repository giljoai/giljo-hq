# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
AI Tools Configuration Generator helpers.

Canonical source for the per-tool MCP `add` commands / config JSON that the
frontend connect wizard (frontend/src/composables/useMcpConfig.js) byte-mirrors.

BE-9143: the registered-but-dead REST routes (GET /supported,
GET /config-generator/{tool}, GET /config-generator/{tool}/markdown) were retired
— the frontend reimplemented them client-side (useMcpConfig.js, "byte-for-byte
parity") and stopped calling the routes. Only these pure helper functions remain;
they are imported directly by the parity tests and are not exposed over HTTP.
"""

import json

from giljo_mcp import branding


# Configuration Templates


def get_claude_code_config(server_url: str, api_key: str) -> str:
    """
    Generate Claude Code MCP HTTP transport command.

    Args:
        server_url: GiljoAI server URL
        api_key: User's API key

    Returns:
        Command string for HTTP transport
    """
    return f"""claude mcp add --scope user --transport http {branding.MCP_ALIAS} {server_url}/mcp \\
  --header "Authorization: Bearer {api_key}" """


def get_codex_config(server_url: str, api_key: str) -> str:
    """
    Generate Codex CLI command using --bearer-token-env-var.

    The server accepts Authorization: Bearer as a fallback to X-API-Key,
    so we can use Codex CLI's native --bearer-token-env-var flag.

    Args:
        server_url: GiljoAI server URL
        api_key: User's API key

    Returns:
        Shell commands to export the key and register the MCP server
    """
    return f"codex mcp add {branding.MCP_ALIAS} --url {server_url}/mcp --bearer-token-env-var GILJO_API_KEY"


def get_claude_desktop_config(server_url: str, api_key: str, self_signed_https: bool) -> str:
    """
    Generate Claude Desktop MCP config JSON (mcp-remote bridge over HTTP transport).

    Claude Desktop can't speak HTTP MCP natively; it spawns the `npx mcp-remote`
    bridge subprocess which then connects to GiljoAI's `/mcp` endpoint and forwards
    the Authorization header. The bearer token is read from the AUTH_HEADER env var
    so the literal key never appears in argv (visible to other processes via ps).

    Args:
        server_url: GiljoAI server URL.
        api_key: User's API key.
        self_signed_https: True only when this backend serves HTTPS itself with a
            self-signed/private certificate (features.ssl_enabled=True). In that
            case the bridge needs NODE_TLS_REJECT_UNAUTHORIZED=0 to accept the
            cert. For proxied HTTPS (TLS terminated upstream) and plain HTTP the
            flag is omitted — never weaken TLS verification on a publicly-signed
            chain.

    Returns:
        Pretty-printed JSON string ready to drop into claude_desktop_config.json.
    """
    env: dict[str, str] = {"AUTH_HEADER": f"Bearer {api_key}"}
    if self_signed_https:
        env["NODE_TLS_REJECT_UNAUTHORIZED"] = "0"

    config = {
        "mcpServers": {
            branding.MCP_ALIAS: {
                "command": "npx",
                "args": [
                    "mcp-remote",
                    f"{server_url}/mcp",
                    "--header",
                    "Authorization:${AUTH_HEADER}",
                ],
                "env": env,
            }
        }
    }
    return json.dumps(config, indent=2)


def get_gemini_config(server_url: str, api_key: str) -> str:
    """
    Generate Gemini CLI MCP HTTP transport command.

    Gemini CLI supports custom headers directly; pass Authorization: Bearer
    and set transport to HTTP. Order is: <name> <url>.

    Args:
        server_url: GiljoAI server URL
        api_key: User's API key

    Returns:
        Command string for HTTP transport (single line)
    """
    return f'gemini mcp add -t http -H "Authorization: Bearer {api_key}" {branding.MCP_ALIAS} {server_url}/mcp'


def get_antigravity_config(server_url: str, api_key: str) -> str:
    """
    Generate Antigravity CLI (`agy`) mcp_config.json snippet.

    agy reads remote MCP servers from a dedicated ``mcp_config.json`` (an
    ``mcpServers`` object), NOT via a shell ``add`` command (no ``agy mcp add``
    exists) and NOT inline in ``settings.json`` the way Gemini CLI did. The
    remote field is ``serverUrl`` (Streamable HTTP) with custom
    ``headers.Authorization: Bearer <token>``. Empirically validated against prod
    in the BE-6041a spike (full MCP handshake, HTTP 200).

    Field rules (all confirmed in the spike):
    - Use ``serverUrl`` — NOT ``url``. Having both fields makes agy attempt SSE
      transport and silently fail for tools. Never emit a ``url`` line.
    - No ``type`` field. No trailing slash (``/mcp`` works).
    - Target file: ``~/.gemini/config/mcp_config.json``.

    This JSON is the canonical source the frontend connect wizard byte-mirrors.

    Args:
        server_url: GiljoAI server URL.
        api_key: User's API key.

    Returns:
        Pretty-printed JSON string ready to drop into mcp_config.json.
    """
    config = {
        "mcpServers": {
            branding.MCP_ALIAS: {
                "serverUrl": f"{server_url}/mcp",
                "headers": {"Authorization": f"Bearer {api_key}"},
            }
        }
    }
    return json.dumps(config, indent=2)


# ─── OAuth-flavored generators (BE-6157) ──────────────────────────
# Canonical reference for the OAuth `mcp add` commands. These emit the add
# command WITHOUT any Authorization header / API key; the CLI then runs its own
# OAuth handshake against the server's /oauth endpoints. Byte-mirrored by the
# matching generate*OAuthConfig() in frontend/src/composables/useMcpConfig.js.
# Verified syntax 2026-06-20.


def get_claude_code_oauth_config(server_url: str) -> str:
    """Claude Code CLI MCP add command for the OAuth flow (no bearer header)."""
    return f"claude mcp add --transport http {branding.MCP_ALIAS} {server_url}/mcp --scope user"


def get_codex_oauth_config(server_url: str) -> str:
    """Codex CLI MCP add command for the OAuth flow (no bearer env var)."""
    return f"codex mcp add {branding.MCP_ALIAS} --url {server_url}/mcp"


def get_gemini_oauth_config(server_url: str) -> str:
    """Gemini CLI MCP add command for the OAuth flow (no Authorization header)."""
    return f"gemini mcp add --scope user --transport http {branding.MCP_ALIAS} {server_url}/mcp"


def get_claude_desktop_oauth_config() -> str:
    """Claude Desktop OAuth has no CLI command — return a short real instruction.

    The connector is added in the app/web settings (by name, not URL) and runs
    OAuth in the browser; we never invent a fake `mcp add` command for it.
    """
    return "Add the GiljoAI connector in Claude Desktop or claude.ai settings; it runs OAuth in the browser."


# Per-tool auth-capability metadata (BE-6157). Keyed by canonical tool id.
# Verified by live testing 2026-06-20. Mirrored in
# frontend/src/composables/useMcpConfig.js → AUTH_CAPABILITIES (keep in sync).
AUTH_CAPABILITIES: dict[str, dict] = {
    "claude": {
        "vendor": "Anthropic",
        "supports_oauth": True,
        "supports_bearer": True,
        "default_auth": "oauth",
        "oauth_quirk_note": (
            "If the browser does not open, the URL is printed; or authenticate at claude.ai and it syncs."
        ),
    },
    "claude_desktop": {
        "vendor": "Anthropic",
        "supports_oauth": True,
        "supports_bearer": True,
        "default_auth": "oauth",
        "oauth_quirk_note": "",
    },
    "codex": {
        "vendor": "OpenAI",
        "supports_oauth": True,
        "supports_bearer": True,
        "default_auth": "oauth",
        "oauth_quirk_note": "OAuth auto-detected on add.",
    },
    "gemini": {
        "vendor": "Google",
        "supports_oauth": True,
        "supports_bearer": True,
        "default_auth": "oauth",
        "oauth_quirk_note": "",
    },
    "antigravity": {
        "vendor": "Google",
        "supports_oauth": False,
        "supports_bearer": True,
        "default_auth": "bearer",
        "oauth_quirk_note": "Antigravity has no OAuth; bearer key in mcp_config.json only.",
    },
    "generic_mcp": {
        "vendor": "Other",
        "supports_oauth": False,
        "supports_bearer": True,
        "default_auth": "bearer",
        "oauth_quirk_note": "",
    },
}


def get_http_tool_instructions(tool_id: str) -> list[str]:
    """
    Get HTTP transport setup instructions for a specific tool.

    Args:
        tool_id: Tool identifier

    Returns:
        List of instruction steps
    """
    if tool_id == "claude":
        return [
            "Open your terminal or command prompt",
            "Copy the command shown above",
            "Paste and run the command to configure Claude Code CLI",
            "Verify connection with: claude mcp list",
            "Start using GiljoAI tools in Claude Code CLI conversations",
        ]
    if tool_id == "claude_desktop":
        return [
            "Open Claude Desktop's configuration file (Settings → Developer → Edit Config)",
            "Merge the JSON shown above into the existing mcpServers object",
            "Save the file and fully quit Claude Desktop (not just close the window)",
            f"Relaunch Claude Desktop and confirm the {branding.MCP_ALIAS} server appears as connected",
            "If npx is missing on Windows, install Node.js LTS first",
        ]
    if tool_id == "codex":
        return [
            "Run the export command to set your API key as an environment variable",
            "Run the codex mcp add command to register the MCP server",
            "The --bearer-token-env-var flag tells Codex to read the key from the environment",
            "Restart Codex CLI to pick up the new configuration",
            "Verify connection with: codex mcp list",
        ]
    if tool_id == "gemini":
        return [
            "Open your terminal or command prompt",
            "Run the gemini mcp add command shown above (note: order is <name> <url>)",
            "Verify connection with: gemini mcp list",
            "Start using GiljoAI tools in Gemini sessions",
        ]
    if tool_id == "antigravity":
        return [
            "Open (or create) the file ~/.gemini/config/mcp_config.json",
            "Merge the JSON shown above into the existing mcpServers object",
            "Use the serverUrl field exactly as shown — do NOT add a url field (a url line causes a silent failure)",
            f"Restart Antigravity CLI (agy), then run: agy plugin list to confirm {branding.MCP_ALIAS} loaded",
            "Start using GiljoAI tools in agy sessions",
        ]
    return ["Copy the command above", "Run it in your terminal", "Verify the connection", "Start using GiljoAI tools"]


CONFIG_GENERATORS: dict[str, dict[str, str]] = {
    "claude": {
        "format": "command",
        "file_location": "Terminal",
        "filename": "giljo-claude-setup.md",
    },
    "claude_desktop": {
        "format": "json",
        "file_location": "claude_desktop_config.json",
        "filename": "giljo-claude-desktop-setup.md",
    },
    "codex": {
        "format": "command",
        "file_location": "Terminal",
        "filename": "giljo-codex-setup.md",
    },
    "gemini": {
        "format": "command",
        "file_location": "Terminal",
        "filename": "giljo-gemini-setup.md",
    },
    "antigravity": {
        "format": "json",
        "file_location": "~/.gemini/config/mcp_config.json",
        "filename": "giljo-antigravity-setup.md",
    },
}
