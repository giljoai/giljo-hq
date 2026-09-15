import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ status: null }))

vi.mock('@/services/api', () => ({
  default: {
    connect: {
      credentialStatus: vi.fn(async () => ({ data: h.status })),
      removeConnection: vi.fn(async () => ({ data: { removed: 1 } })),
    },
  },
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { setup_selected_tools: ['claude_code', 'codex_cli', 'opencode'] },
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
    expect(wrapper.vm.connectedToolIds.size).toBe(0)
    expect(wrapper.vm.statusFor('claude_code')).not.toBe('configured')
    expect(wrapper.vm.statusFor('codex_cli')).not.toBe('configured')
  })

  it('only the tool that actually connected reads configured', async () => {
    const wrapper = await mountDir(ONE_TOOL_CONNECTED)
    expect(wrapper.vm.statusFor('opencode')).toBe('configured')
    expect(wrapper.vm.statusFor('claude_code')).not.toBe('configured')
    expect(wrapper.vm.statusFor('codex_cli')).not.toBe('configured')
  })

  it('statusFor answers for the id it is GIVEN, not for the selected tool', async () => {
    const wrapper = await mountDir(ONE_TOOL_CONNECTED)
    wrapper.vm.selectedId = 'claude_code'
    await flushPromises()
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
      },
    })
    expect(wrapper.vm.statusFor('claude_code')).toBe('configured')
    expect(wrapper.vm.statusFor('codex_cli')).toBe('configured')
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
    const wrapper = await mountDir({
      has_valid_api_key: true,
      has_valid_oauth: false,
      has_expired_oauth: false,
    })
    expect(wrapper.vm.connectedToolIds.size).toBe(0)
    expect(wrapper.vm.statusFor('opencode')).not.toBe('configured')
  })
})
