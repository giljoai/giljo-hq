/**
 * ToolsConnectDirectory.per-tool.spec.js — FE-9500
 *
 * THE DEFECT (operator, production): connecting ONE tool (OpenCode) turned every
 * card on Tools -> Connect green — Claude Code, Antigravity, tools not installed on
 * that machine at all. Removing a tool did not turn it red.
 *
 * Cause in this component: `isConfigured` answered a WORKSPACE question — "does this
 * account hold any live API key or OAuth grant?" — and that single boolean was bound
 * to every card AND returned by `statusFor(id)` for every id, ignoring the id it was
 * handed.
 *
 * These tests pin the per-tool contract: a card is 'configured' when THAT tool
 * completed an MCP handshake (credential-status.connected_harnesses), never because
 * the account happens to hold a credential.
 *
 * Edition scope: Both (shared frontend/src).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ status: null }))

vi.mock('@/services/api', () => ({
  default: {
    connect: {
      credentialStatus: vi.fn(async () => ({ data: h.status })),
      // BE-9591: removeTool now forgets the durable connection too.
      removeConnection: vi.fn(async () => ({ data: { removed: 1 } })),
    },
  },
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { setup_selected_tools: ['claude_code', 'antigravity_cli', 'opencode'] },
    updateSetupState: vi.fn(async () => ({})),
  }),
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({ on: () => () => {} }),
}))

import ToolsConnectDirectory from '../ToolsConnectDirectory.vue'

const stubs = {
  'v-icon': { template: '<i><slot /></i>' },
  'v-btn': { template: '<button><slot /></button>' },
  ConnectToolCard: {
    props: ['toolId', 'connected'],
    template: '<div class="stub-card" :data-tool="toolId" :data-connected="String(connected)" />',
  },
}

async function mountDir(status) {
  h.status = status
  const wrapper = mount(ToolsConnectDirectory, { global: { stubs } })
  await flushPromises()
  return wrapper
}

/** The account holds a live credential, and OpenCode is the only tool that connected. */
const ONE_TOOL_CONNECTED = {
  has_valid_api_key: true,
  has_valid_oauth: true,
  has_expired_oauth: false,
  connected_harnesses: { opencode: '2026-08-25T02:00:00Z' },
}

beforeEach(() => {
  h.status = null
  vi.clearAllMocks()
})

describe('per-tool connect truth', () => {
  it('a credential alone does NOT mark a tool connected', async () => {
    const wrapper = await mountDir({
      has_valid_api_key: true,
      has_valid_oauth: true,
      has_expired_oauth: false,
      connected_harnesses: {},
    })
    // This is the exact production shape: credential present, nothing handshaked.
    expect(wrapper.vm.connectedToolIds.size).toBe(0)
    expect(wrapper.vm.statusFor('claude_code')).not.toBe('configured')
    expect(wrapper.vm.statusFor('antigravity_cli')).not.toBe('configured')
  })

  it('only the tool that actually connected reads configured', async () => {
    const wrapper = await mountDir(ONE_TOOL_CONNECTED)
    expect(wrapper.vm.statusFor('opencode')).toBe('configured')
    // THE REGRESSION: these two were green in production off the workspace flag.
    expect(wrapper.vm.statusFor('claude_code')).not.toBe('configured')
    expect(wrapper.vm.statusFor('antigravity_cli')).not.toBe('configured')
  })

  it('statusFor answers for the id it is GIVEN, not for the selected tool', async () => {
    const wrapper = await mountDir(ONE_TOOL_CONNECTED)
    wrapper.vm.selectedId = 'claude_code'
    await flushPromises()
    // Selecting an unconnected tool must not make it configured, and must not
    // un-configure the tool that really did connect.
    expect(wrapper.vm.statusFor('claude_code')).not.toBe('configured')
    expect(wrapper.vm.statusFor('opencode')).toBe('configured')
  })

  it('maps every backend harness token onto its tool card', async () => {
    const wrapper = await mountDir({
      has_valid_api_key: false,
      has_valid_oauth: true,
      has_expired_oauth: false,
      connected_harnesses: {
        'claude-code': '2026-08-25T01:00:00Z',
        codex: '2026-08-25T01:00:00Z',
        antigravity: '2026-08-25T01:00:00Z',
      },
    })
    // Backend tokens differ from frontend ids ('claude-code' vs 'claude_code') —
    // a silent mismatch here would leave a real connect invisible.
    expect(wrapper.vm.statusFor('claude_code')).toBe('configured')
    expect(wrapper.vm.statusFor('codex_cli')).toBe('configured')
    expect(wrapper.vm.statusFor('antigravity_cli')).toBe('configured')
    expect(wrapper.vm.statusFor('opencode')).not.toBe('configured')
  })

  it('an unknown harness token is ignored rather than lighting a random card', async () => {
    const wrapper = await mountDir({
      has_valid_api_key: false,
      has_valid_oauth: true,
      has_expired_oauth: false,
      connected_harnesses: { 'some-future-tool': '2026-08-25T01:00:00Z' },
    })
    expect(wrapper.vm.connectedToolIds.size).toBe(0)
  })

  it('a missing connected_harnesses field does not crash or mark anything connected', async () => {
    // Rolling deploy: new frontend against an older backend that lacks the field.
    const wrapper = await mountDir({
      has_valid_api_key: true,
      has_valid_oauth: false,
      has_expired_oauth: false,
    })
    expect(wrapper.vm.connectedToolIds.size).toBe(0)
    expect(wrapper.vm.statusFor('opencode')).not.toBe('configured')
  })
})
