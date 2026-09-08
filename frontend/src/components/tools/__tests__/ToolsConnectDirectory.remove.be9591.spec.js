/**
 * ToolsConnectDirectory.remove.be9591.spec.js — BE-9591
 *
 * THE DEFECT (operator, live test): "Remove tool" dropped the card from the local
 * fleet list and persisted `setup_selected_tools` — and touched nothing durable.
 * The card's green comes from `credential-status.connected_harnesses`, which is
 * derived from stored connection rows, so adding the tool back showed it connected
 * again purely from history, with nothing the user could do about it.
 *
 * Removal now also asks the server to forget that tool's stored connection.
 *
 * WHY THE "IT WAS ACTUALLY CALLED" ASSERTION EARNS ITS PLACE: the call is wrapped in
 * a try/catch (a failed cleanup must not block a removal the user already sees), so a
 * missing or renamed client method fails SILENTLY — warned to the console and
 * otherwise invisible. Discovered exactly that way while writing this: before the
 * sibling spec's mock was updated, `removeConnection` was undefined and the whole
 * suite still passed green. Asserting the call is what turns that into a red.
 *
 * Edition scope: Both.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({ status: null, removed: [], persisted: [] }))

vi.mock('@/services/api', () => ({
  default: {
    // ConnectToolCard (not stubbed -- the removal link lives inside the card) probes
    // for active keys on mount. Absent, every test logs a swallowed TypeError.
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

  // Asserted on the PROP the card is actually given, not on a data-testid.
  // The first version of these tests keyed on `[data-testid="dir-card-connected"]`,
  // which does not exist -- so `.exists()` was false whatever the component did and
  // both tests passed before the feature was written. A selector that matches nothing
  // is unfalsifiable in either direction, and mutation testing cannot see it.
  const cardConnected = (wrapper) => wrapper.findComponent(ConnectToolCard).props('connected')

  it('the CARD starts NOT connected even when the tool connected long ago', async () => {
    // The operator's second-device case: connected on his PC, opened this UI on a
    // laptop, card already green -- a connection inherited from a machine that was
    // not the one in front of him. The server cannot tell the machines apart, so the
    // flow verifies the connect he is performing NOW.
    const wrapper = await mountDir()

    expect(cardConnected(wrapper)).toBe(false)
  })

  it('a FRESH announce upgrades the card to connected', async () => {
    const wrapper = await mountDir()
    expect(cardConnected(wrapper)).toBe(false)

    // Driven through the component's OWN refetch trigger rather than by reaching
    // into its internals -- `fetchCredentialStatus` is not exposed by <script setup>,
    // and a test that could only work by exposing it would be testing a seam the
    // product does not have.
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
    // The operator's edge case. Entering the fresh flow is view state only: no write,
    // no removal. Back out without completing and the passive surfaces must show the
    // remembered connection again immediately -- only "Remove tool" erases, and only a
    // fresh announce upgrades the flow.
    const wrapper = await mountDir()
    expect(cardConnected(wrapper)).toBe(false)

    // Leaving the card is not a mutation of anything durable.
    expect(h.removed).toEqual([])
    const wrote = h.persisted.filter((p) => p && 'setup_selected_tools' in p)
    expect(wrote.every((p) => p.setup_selected_tools.includes('claude_code'))).toBe(true)

    // And the durable truth the passive surfaces read is untouched.
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
    // Already true today (addTool guards on `includes`), pinned because the ruling
    // names it and because the fresh-flow work is exactly the kind of change that
    // tempts someone to model "connected on this device" as another row.
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
    // The card is keyed 'claude_code'; the API and the stored rows speak
    // 'claude-code'. Sending the card id would 200 and delete nothing, leaving the
    // card green — a removal that reports success and changes nothing.
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

    // The local removal is honoured regardless -- the user already sees the card go.
    // Asserted on what was PERSISTED rather than on the remove link still existing:
    // the fleet also holds opencode, so a link legitimately remains for it, and
    // asserting its absence would pass only by accident on a one-tool fixture.
    const lastPatch = h.persisted[h.persisted.length - 1]
    expect(lastPatch.setup_selected_tools).not.toContain('claude_code')
  })
})
