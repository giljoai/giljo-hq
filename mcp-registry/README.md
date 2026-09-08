# MCP Registry manifest

`server.json` is the publish manifest for listing Giljo HQ in the official
[MCP Registry](https://registry.modelcontextprotocol.io) under the namespace
`ai.giljo/hq`.

- The file is inert in the repository: nothing reads it at runtime. Publication
  happens explicitly via the `mcp-publisher` CLI
  (https://modelcontextprotocol.io/registry/quickstart), authenticated by
  domain verification for `giljo.ai`.
- `version` must always match the repository `VERSION` file. A unit test
  (`tests/unit/test_server_json_version_drift.py`) fails the suite when they
  drift, and also pins the remote URL to the plain `https://app.giljo.ai/mcp`
  form.
- Registry names are permanent: `ai.giljo/hq` cannot be renamed after first
  publish, only abandoned for a new name.
