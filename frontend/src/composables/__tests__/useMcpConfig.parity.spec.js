import { describe, expect, it } from 'vitest'
import fixture from '../../../../tests/fixtures/mcp_setup_command_parity.json'
import {
  generateClaudeConfig,
  generateClaudeDesktopConfig,
  generateClaudeDesktopOAuthConfig,
  generateClaudeOAuthConfig,
  generateCodexConfig,
  generateCodexOAuthConfig,
  generateGenericMcpConfig,
  generateOpenCodeConfig,
  generateOpenCodeOAuthConfig,
} from '../useMcpConfig'

const { server_url: SERVER_URL, api_key: API_KEY } = fixture.inputs

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


    it('opencode matches backend command', () => {
      const actual = generateOpenCodeConfig(SERVER_URL, API_KEY)
      expect(normalizeCommand(actual)).toBe(normalizeCommand(fixture.commands.opencode))
    })

    it('opencode_oauth matches backend commands (BE-9726: connect.md serves these)', () => {
      const actual = generateOpenCodeOAuthConfig(SERVER_URL)
      expect(normalizeCommand(actual)).toBe(normalizeCommand(fixture.commands.opencode_oauth))
    })
  })

  describe('JSON-config tools (structural equality)', () => {
    it('claude_desktop JSON structure matches backend fixture', () => {
      const actual = JSON.parse(
        generateClaudeDesktopConfig(SERVER_URL, API_KEY),
      )
      const expected = JSON.parse(fixture.commands.claude_desktop)
      expect(actual).toEqual(expected)
    })

    it('generic_mcp JSON structure matches backend fixture (BE-9726)', () => {
      const actual = JSON.parse(generateGenericMcpConfig(SERVER_URL, API_KEY))
      expect(actual).toEqual(JSON.parse(fixture.commands.generic_mcp))
    })
  })

  describe('prose tool (verbatim — a mismatch here is real wording drift, not formatting)', () => {
    it('claude_desktop_oauth prose matches backend fixture', () => {
      const actual = generateClaudeDesktopOAuthConfig()
      expect(actual).toBe(fixture.commands.claude_desktop_oauth)
    })
  })
})
