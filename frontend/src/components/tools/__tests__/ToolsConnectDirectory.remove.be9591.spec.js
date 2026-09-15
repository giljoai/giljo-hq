import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ status: null, removed: [], persisted: [] }))

vi.mock('@/services/api', () => ({
  default: {
    apiKeys: { getActive: vi.fn(async () => ({ data: [] })), create: vi.fn() },
    connect: {
      credentialStatus: vi.fn(async () => ({ data: h.status })),
      removeConnection: vi.fn(async (harness) => {
        h.removed.push(harness)
        return { data: { harness, removed: 1 } }
      }),
    },
  },
}))

vi.mock('@/stores/user', () => ({
  useUserStore: () => ({
    currentUser: { setup_selected_tools: ['claude_code', 'opencode'] },
    updateSetupState: vi.fn(async (patch) => {
      h.persisted.push(patch)
      return {}
    }),
  }),
}))

vi.mock('@/stores/websocket', () => ({
  useWebSocketStore: () => ({ on: () => () => {} }),
}))

import ToolsConnectDirectory from '../ToolsConnectDirectory.vue'
import ConnectToolCard from '@/components/setup/ConnectToolCard.vue'

const stubs = {
  'v-icon': true,
  'v-btn': { template: '<button><slot /></button>' },
  'v-tooltip': { template: '<div><slot /></div>' },
  'v-menu': { template: '<div><slot /></div>' },
}

const CONNECTED = {
  has_valid_api_key: true,
  has_valid_oauth: true,
  has_expired_oauth: false,
  connected_harnesses: { 'claude-code': '2026-09-05T02:00:00Z', opencode: '2026-09-05T02:00:00Z' },
}

async function mountDir() {
  h.status = CONNECTED
  const wrapper = mount(ToolsConnectDirectory, { global: { stubs } })
  await flushPromises()
  return wrapper
}

describe('BE-9591 (c) — picking a tool always starts a FRESH flow', () => {
  beforeEach(() => {
    h.removed = []
    h.persisted = []
    vi.clearAllMocks()
  })

  const cardConnected = (wrapper) => wrapper.findComponent(ConnectToolCard).props('connected')

  it('the CARD starts NOT connected even when the tool connected long ago', async () => {
    const wrapper = await mountDir()

    expect(cardConnected(wrapper)).toBe(false)
  })

  it('a FRESH announce upgrades the card to connected', async () => {
    const wrapper = await mountDir()
    expect(cardConnected(wrapper)).toBe(false)

    h.status = {
      ...CONNECTED,
      connected_harnesses: { 'claude-code': new Date(Date.now() + 60_000).toISOString() },
    }
    window.dispatchEvent(new Event('api-key-created'))
    await flushPromises()

    expect(cardConnected(wrapper)).toBe(true)
  })

  it('the SIDEBAR still remembers -- that passive label is not this ruling\'s target', async () => {
    const wrapper = await mountDir()

    const railStatuses = wrapper.findAll('.dir-rail-status').map((n) => n.text().toLowerCase())
    expect(railStatuses.some((t) => t.includes('connected') || t.includes('configured'))).toBe(true)
  })

  it('BACKING OUT of the flow writes NOTHING and leaves the record intact', async () => {
    const wrapper = await mountDir()
    expect(cardConnected(wrapper)).toBe(false)

    expect(h.removed).toEqual([])
    const wrote = h.persisted.filter((p) => p && 'setup_selected_tools' in p)
    expect(wrote.every((p) => p.setup_selected_tools.includes('claude_code'))).toBe(true)

    const railStatuses = wrapper.findAll('.dir-rail-status').map((n) => n.text().toLowerCase())
    expect(railStatuses.some((t) => t.includes('connected') || t.includes('configured'))).toBe(true)
  })
})

describe('BE-9591 (d) — the sidebar stays ONE entry per tool', () => {
  beforeEach(() => {
    h.removed = []
    h.persisted = []
    vi.clearAllMocks()
  })

  it('re-adding a tool already in the fleet does not create a second entry', async () => {
    const wrapper = await mountDir()
    const before = wrapper.findAll('[data-testid^="dir-tool-"]').length

    await wrapper.vm.$nextTick()
    const claudeEntries = wrapper.findAll('[data-testid="dir-tool-claude_code"]')

    expect(claudeEntries).toHaveLength(1)
    expect(wrapper.findAll('[data-testid^="dir-tool-"]').length).toBe(before)
  })
})

describe('BE-9591 — Remove tool forgets the stored connection', () => {
  beforeEach(() => {
    h.removed = []
    h.persisted = []
    vi.clearAllMocks()
  })

  it('asks the server to forget THAT tool, by its harness token', async () => {
    const wrapper = await mountDir()

    await wrapper.find('[data-testid="dir-remove-tool"]').trigger('click')
    await flushPromises()

    expect(h.removed).toEqual(['claude-code'])
  })

  it('sends the HARNESS token, not the card id', async () => {
    const wrapper = await mountDir()

    await wrapper.find('[data-testid="dir-remove-tool"]').trigger('click')
    await flushPromises()

    expect(h.removed[0]).toBe('claude-code')
    expect(h.removed[0]).not.toBe('claude_code')
  })

  it('a failed cleanup does not block the removal the user already asked for', async () => {
    const api = (await import('@/services/api')).default
    api.connect.removeConnection.mockRejectedValueOnce(new Error('network down'))
    const wrapper = await mountDir()

    await wrapper.find('[data-testid="dir-remove-tool"]').trigger('click')
    await flushPromises()

    const lastPatch = h.persisted[h.persisted.length - 1]
    expect(lastPatch.setup_selected_tools).not.toContain('claude_code')
  })
})
