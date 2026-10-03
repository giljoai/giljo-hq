# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json

from giljo_mcp import branding




def get_claude_code_config(server_url: str, api_key: str) -> str:
    return f"""claude mcp add --scope user --transport http {branding.MCP_ALIAS} {server_url}/mcp \\
  --header "Authorization: Bearer {api_key}" """


def get_codex_config(server_url: str, api_key: str) -> str:
    return f"codex mcp add {branding.MCP_ALIAS} --url {server_url}/mcp --bearer-token-env-var GILJO_API_KEY"


def get_claude_desktop_config(server_url: str, api_key: str) -> str:
    env: dict[str, str] = {"AUTH_HEADER": f"Bearer {api_key}"}

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




def get_claude_code_oauth_config(server_url: str) -> str:
    return f"claude mcp add --transport http {branding.MCP_ALIAS} {server_url}/mcp --scope user"


def get_codex_oauth_config(server_url: str) -> str:
    return f"codex mcp add {branding.MCP_ALIAS} --url {server_url}/mcp"


def get_claude_desktop_oauth_config() -> str:
    return "Add the GiljoAI connector in Claude Desktop or claude.ai settings; it runs OAuth in the browser."


def get_opencode_oauth_config(server_url: str) -> str:
    return f"opencode mcp add {branding.MCP_ALIAS} --url {server_url}/mcp\nopencode mcp auth {branding.MCP_ALIAS}"


def get_opencode_config(server_url: str, api_key: str) -> str:
    return f'opencode mcp add {branding.MCP_ALIAS} --url {server_url}/mcp --header "Authorization=Bearer {api_key}"'


def get_generic_mcp_config(server_url: str, api_key: str) -> str:
    config = {
        branding.MCP_ALIAS: {
            "transport": "streamable-http",
            "url": f"{server_url}/mcp",
            "headers": {"Authorization": f"Bearer {api_key}"},
        }
    }
    return json.dumps(config, indent=2)


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
    "generic_mcp": {
        "vendor": "Other",
        "supports_oauth": False,
        "supports_bearer": True,
        "default_auth": "bearer",
        "oauth_quirk_note": "",
    },
}


def get_http_tool_instructions(tool_id: str) -> list[str]:
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
}
