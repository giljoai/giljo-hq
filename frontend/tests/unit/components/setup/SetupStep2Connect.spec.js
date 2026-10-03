/**
 * Unit tests for SetupStep2Connect — the walk-one-tool-at-a-time connect step
 * (rebuilt FE-9204; hosts the shared ConnectToolCard). This file keeps the
 * invariants unique to it — INF-5012b server-URL port mirroring and the WS
 * unsubscribe-on-unmount — under the new anatomy. Broader connect behavior is
 * covered by src/components/setup/__tests__/SetupStep2Connect.spec.js.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { nextTick } from 'vue'
import SetupStep2Connect from '@/components/setup/SetupStep2Connect.vue'
import api from '@/services/api'
import configService from '@/services/configService'

// ─── Mock stores ──────────────────────────────────────────────────

const mockUnsub = vi.fn()
const mockWsOn = vi.fn(() => mockUnsub)

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({
    on: mockWsOn,
    off: vi.fn(),
    isConnected: true,
  }),
}))

vi.mock('@/composables/useClipboard', () => ({
  useClipboard: () => ({ copy: vi.fn(() => Promise.resolve(true)) }),
}))

vi.mock('@/services/configService', () => ({
  default: { fetchConfig: vi.fn() },
}))

function mountStep2(props = {}) {
  return mount(SetupStep2Connect, {
    props: { selectedTools: ['claude_code'], ...props },
    global: {
      plugins: [createPinia()],
      stubs: {
        'v-expand-transition': { template: '<div><slot /></div>' },
      },
    },
  })
}

// Reveal the API-key fallback for a sign-in-capable tool (SaaS default is sign-in).
async function revealKeyFlow(wrapper) {
  const toggle = wrapper.find('[data-testid="fallback-toggle"]')
  if (toggle.exists()) {
    await toggle.trigger('click')
    await flushPromises()
  }
}

// ─── Tests ────────────────────────────────────────────────────────

describe('SetupStep2Connect', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.apiKeys.getActive = vi.fn().mockResolvedValue({ data: [{ key_prefix: 'giljo_abc' }] })
    api.apiKeys.create = vi.fn().mockResolvedValue({ data: { api_key: 'giljo_full_key_123' } })
    configService.fetchConfig.mockResolvedValue(null) // keep window.location.* fallback
  })

  it('renders the connect eyebrow + title for the active tool', async () => {
    const wrapper = mountStep2()
    await flushPromises()
    expect(wrapper.find('.connect-eyebrow').text()).toContain('TOOL 1 OF 1')
    expect(wrapper.find('.connect-title').text()).toContain('Connect Claude Code')
  })

  it('walks tools one at a time (no tab bar)', async () => {
    const wrapper = mountStep2({ selectedTools: ['claude_code', 'codex_cli'] })
    await flushPromises()
    expect(wrapper.find('.tool-tabs').exists()).toBe(false)
    expect(wrapper.find('.connect-eyebrow').text()).toContain('TOOL 1 OF 2')
  })

  it('reveals the existing key prefix once the API-key fallback is toggled', async () => {
    api.apiKeys.getActive.mockResolvedValue({ data: [{ key_prefix: 'giljo_abc' }] })
    const wrapper = mountStep2()
    await flushPromises()
    await revealKeyFlow(wrapper)
    expect(wrapper.text()).toContain('giljo_abc')
    expect(wrapper.text()).toContain('Key exists')
  })

  it('calls api.apiKeys.create when the generate button is clicked', async () => {
    api.apiKeys.getActive.mockResolvedValue({ data: [] })
    const wrapper = mountStep2()
    await flushPromises()
    await revealKeyFlow(wrapper)
    const generateBtn = wrapper.findAll('button').find((b) => b.text().includes('Generate API Key'))
    expect(generateBtn).toBeTruthy()
    await generateBtn.trigger('click')
    await flushPromises()
    expect(api.apiKeys.create).toHaveBeenCalled()
  })

  it('renders the bearer config command for the active tool once a key exists', async () => {
    api.apiKeys.getActive.mockResolvedValue({ data: [] })
    const wrapper = mountStep2({ selectedTools: ['codex_cli'] })
    await flushPromises()
    await revealKeyFlow(wrapper)
    const generateBtn = wrapper.findAll('button').find((b) => b.text().includes('Generate API Key'))
    await generateBtn.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('codex mcp add')
  })

  it('flips the status hero to connected when the WS event fires', async () => {
    api.apiKeys.getActive.mockResolvedValue({ data: [] })
    const wrapper = mountStep2({ selectedTools: ['claude_code'] })
    await flushPromises()
    expect(wrapper.find('[data-testid="hero-dot"]').exists()).toBe(true)

    const onCall = mockWsOn.mock.calls.find((call) => call[0] === 'setup:tool_connected')
    expect(onCall).toBeTruthy()
    onCall[1]({ tool_name: 'generic' })
    await nextTick()
    expect(wrapper.find('[data-testid="hero-check"]').exists()).toBe(true)
  })

  it('emits can-proceed false initially and true after connection', async () => {
    const wrapper = mountStep2({ selectedTools: ['claude_code'] })
    await flushPromises()
    const canProceed = wrapper.emitted('can-proceed')
    expect(canProceed[0]).toEqual([false])

    const handler = mockWsOn.mock.calls.find((call) => call[0] === 'setup:tool_connected')[1]
    handler({ tool_name: 'generic' })
    await nextTick()
    const all = wrapper.emitted('can-proceed')
    expect(all[all.length - 1]).toEqual([true])
  })

  it('emits step-data with the connected tools list', async () => {
    const wrapper = mountStep2({ selectedTools: ['claude_code'] })
    await flushPromises()
    const handler = mockWsOn.mock.calls.find((call) => call[0] === 'setup:tool_connected')[1]
    handler({ tool_name: 'generic' })
    await nextTick()
    const stepData = wrapper.emitted('step-data')
    const last = stepData[stepData.length - 1][0]
    expect(last.connectedTools).toContain('claude_code')
  })

  it('unsubscribes from the WebSocket on unmount', async () => {
    const wrapper = mountStep2()
    await flushPromises()
    expect(mockWsOn).toHaveBeenCalled()
    wrapper.unmount()
    expect(mockUnsub).toHaveBeenCalled()
  })

  // INF-5012b: server URL mirrors backend identity — null port omits :7272
  // (reverse-proxy std 443/80), numeric port kept when host differs. The rule
  // now lives in ConnectToolCard's serverUrl; the command text reflects it.
  it('mirrors null backend port as empty string — no stale :7272 (INF-5012b)', async () => {
    api.apiKeys.getActive.mockResolvedValue({ data: [] })
    configService.fetchConfig.mockResolvedValue({
      api: { host: 'mcp.example.com', port: null, protocol: 'https' },
    })
    const wrapper = mountStep2({ selectedTools: ['claude_code'] })
    await flushPromises()
    // The sign-in command carries the server URL — assert on it directly.
    const cmd = wrapper.find('pre.config-code').text()
    expect(cmd).toContain('mcp.example.com')
    expect(cmd).not.toContain('mcp.example.com:7272')
  })

  it('mirrors numeric backend port when host differs from the browser (INF-5012b)', async () => {
    api.apiKeys.getActive.mockResolvedValue({ data: [] })
    configService.fetchConfig.mockResolvedValue({
      api: { host: '192.0.2.50', port: 7272, protocol: 'http' },
    })
    const wrapper = mountStep2({ selectedTools: ['claude_code'] })
    await flushPromises()
    expect(wrapper.find('pre.config-code').text()).toContain('192.0.2.50:7272')
  })
})
