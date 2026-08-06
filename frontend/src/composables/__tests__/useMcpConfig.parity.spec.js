/**
 * BE-9281 item 2 — byte-mirror parity between the backend MCP-setup-command
 * generators (api/endpoints/ai_tools.py) and their frontend twins in
 * useMcpConfig.js. Both sides consume the SAME shared fixture
 * (tests/fixtures/mcp_setup_command_parity.json), committed once by the
 * backend implementer — do not duplicate it here.
 *
 * Known cosmetic divergence (not drift): the backend's
 * get_claude_code_config emits a multi-line shell command with a
 * `\`-continuation + trailing space before the header flag; the frontend
 * generateClaudeConfig emits the same command single-line. We normalize
 * whitespace (collapsing all runs, including the backslash-continuation,
 * to a single space, then trim) before comparing CLI-command tools so this
 * formatting difference doesn't trip the guard — while real drift (wrong
 * alias, wrong route, missing/extra flag, wrong auth header) still fails
 * because it survives normalization.
 *
 * JSON-emitting tools (antigravity_cli, claude_desktop) are compared by
 * parsed structure, not raw string, for the same reason (key order /
 * indentation is not the guarantee we're after — the shape and values are).
 *
 * The desktop_oauth entry is a prose string, not a command — compared
 * verbatim; a genuine wording difference is real drift, not formatting.
 */
import { describe, expect, it } from 'vitest'
import fixture from '../../../../tests/fixtures/mcp_setup_command_parity.json'
import {
  generateAntigravityConfig,
  generateClaudeConfig,
  generateClaudeDesktopConfig,
  generateClaudeDesktopOAuthConfig,
  generateClaudeOAuthConfig,
  generateCodexConfig,
  generateCodexOAuthConfig,
  generateGeminiConfig,
  generateGeminiOAuthConfig,
} from '../useMcpConfig'

const { server_url: SERVER_URL, api_key: API_KEY } = fixture.inputs

/** Collapse all whitespace runs (incl. `\`+newline continuations) to a single space, trim. */
function normalizeCommand(raw) {
  return String(raw)
    .replace(/\\\s*\n\s*/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

describe('useMcpConfig — byte-mirror parity with backend fixture (BE-9281)', () => {
  describe('CLI-command tools (whitespace-normalized)', () => {
    it('claude_code matches backend claude mcp add command', () => {
      const actual = generateClaudeConfig(SERVER_URL, API_KEY)
      expect(normalizeCommand(actual)).toBe(normalizeCommand(fixture.commands.claude_code))
    })

    it('claude_code_oauth matches backend command', () => {
      const actual = generateClaudeOAuthConfig(SERVER_URL)
      expect(normalizeCommand(actual)).toBe(normalizeCommand(fixture.commands.claude_code_oauth))
    })

    it('codex_cli matches backend command', () => {
      const actual = generateCodexConfig(SERVER_URL)
      expect(normalizeCommand(actual)).toBe(normalizeCommand(fixture.commands.codex_cli))
    })

    it('codex_oauth matches backend command', () => {
      const actual = generateCodexOAuthConfig(SERVER_URL)
      expect(normalizeCommand(actual)).toBe(normalizeCommand(fixture.commands.codex_oauth))
    })

    it('gemini_cli matches backend command', () => {
      const actual = generateGeminiConfig(SERVER_URL, API_KEY)
      expect(normalizeCommand(actual)).toBe(normalizeCommand(fixture.commands.gemini_cli))
    })

    it('gemini_oauth matches backend command', () => {
      const actual = generateGeminiOAuthConfig(SERVER_URL)
      expect(normalizeCommand(actual)).toBe(normalizeCommand(fixture.commands.gemini_oauth))
    })
  })

  describe('JSON-config tools (structural equality)', () => {
    it('antigravity_cli JSON structure matches backend fixture', () => {
      const actual = JSON.parse(generateAntigravityConfig(SERVER_URL, API_KEY))
      const expected = JSON.parse(fixture.commands.antigravity_cli)
      expect(actual).toEqual(expected)
    })

    it('claude_desktop JSON structure matches backend fixture', () => {
      const actual = JSON.parse(
        generateClaudeDesktopConfig(SERVER_URL, API_KEY, { selfSigned: fixture.inputs.self_signed_https }),
      )
      const expected = JSON.parse(fixture.commands.claude_desktop)
      expect(actual).toEqual(expected)
    })
  })

  describe('prose tool (verbatim — a mismatch here is real wording drift, not formatting)', () => {
    it('claude_desktop_oauth prose matches backend fixture', () => {
      const actual = generateClaudeDesktopOAuthConfig()
      expect(actual).toBe(fixture.commands.claude_desktop_oauth)
    })
  })
})
