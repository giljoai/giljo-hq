/**
 * Product branding constants -- single source of truth for display name and
 * MCP alias text.
 *
 * BE-9275a: chain step 1 of the "GiljoAI MCP" -> "Giljo HQ" identity flip.
 * "HQ" is literal in product copy -- never spell out "Headquarters".
 *
 * FROZEN, never derived from here: the `src/giljo_mcp` package name, the DB
 * name `giljo_mcp`, `GILJO_*`/`GILJO_MCP_*` env var names, migration revision
 * ids, pyproject/package.json package names, the `/mcp` route, the OAuth
 * client id `giljo-mcp-default`, and the `GILJOAI_MCP_PRIMER_START`/`END`
 * marker names. Those identifiers are contract-level, not branding, and this
 * module must never be imported to generate them.
 *
 * Mirrored byte-for-byte in src/giljo_mcp/branding.py -- keep both in sync.
 */

export const HOUSE_BRAND = 'GiljoAI'
export const PRODUCT_NAME = 'Giljo HQ'
export const PRODUCT_SHORT = 'Giljo HQ'
export const MCP_ALIAS = 'giljo_hq'
export const DESCRIPTOR = 'Giljo HQ — project, task, and agent coordination for the one-person software company'

/**
 * Shared disambiguation sentence appended to messaging/task-tool descriptions
 * and to the MCP server's own `instructions=` text (BE-9275a step 2 + step 8).
 * Warns an agent that may also have Giljo AMH (giljo_amh) connected in the
 * same session to check which hub the user means before posting.
 */
export const TWO_HUB_DISAMBIGUATION =
  "This is Giljo HQ's built-in message hub; if another Giljo message-hub " +
  'server (e.g. giljo_amh) is also connected in this session, ask the user ' +
  'which hub to use before posting.'
