/**
 * setupTools.js — canonical tool registry for the setup-experience surfaces
 * (FE-9204). Single source of truth for the six connectable tools shared by the
 * wizard choose-grid (step 0), the shared connect card (ConnectToolCard), and the
 * /tools connect directory. Replaces the per-file TOOL_META copies that had drifted
 * across SetupStep2Connect / SetupStep3Commands.
 *
 * Each tool carries EITHER `logo` (an <img> asset path) OR `icon` (an mdi glyph name)
 * for the icon well. All six tools currently ship a real logo asset.
 */
import { getAuthCapabilities } from '@/composables/useMcpConfig'

// Ordered list — drives the choose grid and the "+ Add a tool" picker.
export const SETUP_TOOLS = [
  { id: 'claude_code', name: 'Claude Code', logo: '/claude-color.svg' },
  { id: 'codex_cli', name: 'Codex CLI', logo: '/icons/codex_mark_white.svg' },
  { id: 'gemini_cli', name: 'Gemini CLI', logo: '/gemini-icon.svg' },
  { id: 'antigravity_cli', name: 'Antigravity CLI', logo: '/antigravity-color.svg' },
  { id: 'opencode', name: 'OpenCode', logo: '/opencode-mark-white.svg' },
  { id: 'generic', name: 'Generic MCP client', logo: '/logo-mcp.svg' },
]

// FE-9500: harness token (backend, harness_resolver.py) -> tool id (frontend).
// TWO VOCABULARIES, ONE SEAM. The backend names a connecting client with its own
// tokens ('claude-code', 'codex', 'gemini', 'antigravity', 'opencode', 'generic');
// this file's ids are 'claude_code', 'codex_cli', ... A silent mismatch here means
// a real connect never lights its card, so tests/unit pins both sides of this map.
//
// 'generic' is deliberately mapped: a client that self-identifies with nothing is a
// REAL connection, and the Generic MCP client card is the honest place to show it.
// Claude Desktop and claude.ai web cannot be separated at all -- they send
// byte-identical initialize payloads -- so both land on claude_code.
const HARNESS_TO_TOOL_ID = {
  'claude-code': 'claude_code',
  codex: 'codex_cli',
  gemini: 'gemini_cli',
  antigravity: 'antigravity_cli',
  opencode: 'opencode',
  generic: 'generic',
}

/** Tool id for a backend harness token, or null when the token is unknown here. */
export function toolIdForHarness(harness) {
  return HARNESS_TO_TOOL_ID[harness] ?? null
}

// BE-9591: the reverse direction, DERIVED from the same object rather than written
// out again. "Remove tool" knows a card id and the API takes a harness token, so the
// mapping is needed both ways -- and a second hand-written literal is exactly how the
// two would drift into disagreeing about which card a connection belongs to.
const TOOL_ID_TO_HARNESS = Object.fromEntries(
  Object.entries(HARNESS_TO_TOOL_ID).map(([harness, toolId]) => [toolId, harness]),
)

/** Backend harness token for a tool id, or null when the id is unknown here. */
export function harnessForToolId(toolId) {
  return TOOL_ID_TO_HARNESS[toolId] ?? null
}

// Keyed lookup for the connect card / directory.
export const TOOL_META = Object.fromEntries(SETUP_TOOLS.map((t) => [t.id, t]))

/**
 * Display name for a tool id (falls back to a neutral label for unknown ids).
 * @param {string} toolId
 * @returns {string}
 */
export function toolName(toolId) {
  return TOOL_META[toolId]?.name || 'your tool'
}

/**
 * Method tag shown on the choose grid card, per edition.
 *   - Generic MCP client: always MANUAL CONFIG (pasted JSON, no CLI command).
 *   - CE: every tool is API KEY (self-hosted, no browser sign-in — FE-6242).
 *   - SaaS: sign-in-capable tools read SIGN-IN OR KEY; key-only tools API KEY ONLY.
 * @param {string} toolId
 * @param {boolean} isCe
 * @returns {string}
 */
export function methodTag(toolId, isCe) {
  if (toolId === 'generic') return 'MANUAL CONFIG'
  if (isCe) return 'API KEY'
  const caps = getAuthCapabilities(toolId)
  return caps?.supports_oauth ? 'SIGN-IN OR KEY' : 'API KEY ONLY'
}
