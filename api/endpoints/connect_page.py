# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import re
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from api.endpoints import ai_tools
from giljo_mcp import branding
from giljo_mcp.http.url_resolver import get_public_base_url


router = APIRouter()

KEY_PLACEHOLDER = "<YOUR_API_KEY>"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
_SAFE_BASE_URL = re.compile(r"https?://[A-Za-z0-9.\-]+(:\d{1,5})?|https?://\[[0-9A-Fa-f:]+\](:\d{1,5})?")


def _oauth_allowed(server_url: str) -> bool:
    parsed = urlparse(server_url)
    return parsed.scheme == "https" or (parsed.hostname or "") in _LOOPBACK_HOSTS


def _fenced(command: str, lang: str = "bash") -> str:
    return f"```{lang}\n{command.strip()}\n```"


def _oauth_sections(server_url: str) -> list[str]:
    return [
        "## Claude Code\n\n"
        + _fenced(ai_tools.get_claude_code_oauth_config(server_url))
        + "\n\nThen run `/mcp` inside Claude Code and choose to authenticate; a browser window opens for sign-in.",
        "## Codex CLI\n\n"
        + _fenced(ai_tools.get_codex_oauth_config(server_url))
        + "\n\nCodex detects OAuth on add and opens the browser to sign in.",
        "## OpenCode\n\n" + _fenced(ai_tools.get_opencode_oauth_config(server_url)),
        "## Claude Desktop and claude.ai\n\n"
        f"Add a custom connector in Settings > Connectors with the address `{server_url}/mcp`. "
        "It signs in through the browser.",
        "## Generic MCP client\n\n"
        f"Server address (streamable HTTP): `{server_url}/mcp`. "
        f"The server advertises OAuth at `{server_url}/.well-known/oauth-authorization-server`; "
        "a client that supports MCP OAuth with dynamic client registration needs nothing else.",
    ]


def _key_sections(server_url: str, api_key: str) -> list[str]:
    return [
        "## Claude Code\n\n" + _fenced(ai_tools.get_claude_code_config(server_url, api_key)),
        "## Codex CLI\n\nSet the key in an environment variable first, then register the server:\n\n"
        + _fenced(f'export GILJO_API_KEY="{api_key}"\n' + ai_tools.get_codex_config(server_url, api_key)),
        "## OpenCode\n\n" + _fenced(ai_tools.get_opencode_config(server_url, api_key)),
        "## Generic MCP client\n\n"
        f"Server address (streamable HTTP): `{server_url}/mcp`. Send the key as a bearer header:\n\n"
        + _fenced(ai_tools.get_generic_mcp_config(server_url, api_key), "json"),
    ]


def render_connect_md(server_url: str, api_key: str = KEY_PLACEHOLDER) -> str:
    alias = branding.MCP_ALIAS
    oauth = _oauth_allowed(server_url)
    if oauth:
        path_rule = (
            "This server is reachable over HTTPS or on this machine (localhost), so use "
            "**sign-in (OAuth)**. Do not ask the user for an API key."
        )
        sections = _oauth_sections(server_url)
    else:
        path_rule = (
            "This server is plain HTTP on a non-local address. Coding tools refuse to run OAuth "
            "against a non-TLS token endpoint, so an **API key is required**. "
            f"Ask the user to generate one in the dashboard ({server_url}, Tools > Connect), paste it to you, "
            f"and substitute it for `{KEY_PLACEHOLDER}` below. Never invent, guess or print a key, "
            "and never write one into a file the user did not ask for."
        )
        sections = _key_sections(server_url, api_key)

    head = (
        f"# Connect to this server\n\n"
        f"Server: `{server_url}`  \nMCP address: `{server_url}/mcp`  \nServer name to register: `{alias}`\n\n"
        "You are an AI coding agent. Follow these steps to connect your own harness to this server.\n\n"
        "## Steps\n\n"
        "1. Pick the section below that matches the harness you are running in.\n"
        "2. Run the command(s) in it.\n"
        "3. Restart or reload the harness if it asks you to, and confirm the server is connected "
        f"(for example `claude mcp list`, `codex mcp list`, `opencode mcp list`).\n"
        "4. Call the `giljo_setup` tool. It installs the rest of the integration (skills and agent profiles) for your harness.\n\n"
        f"## Which sign-in path\n\n{path_rule}\n"
    )
    return head + "\n" + "\n\n".join(sections) + "\n"


@router.get("/connect.md", response_class=PlainTextResponse, tags=["connect"], include_in_schema=False)
async def connect_md(request: Request) -> PlainTextResponse:
    """Plain-markdown instructions an AI agent can follow to connect to this server (public, no key)."""
    server_url = get_public_base_url(request)
    if not _SAFE_BASE_URL.fullmatch(server_url):
        raise HTTPException(status_code=400, detail="Invalid host")
    return PlainTextResponse(
        render_connect_md(server_url),
        media_type="text/markdown; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )
