/**
 * MessageComposer.spec.js — FE-6174b, rewired BE-9012d Part 1
 *
 * Unit tests for the MessageComposer component covering solo and chain
 * routing. BE-9012d Part 1 rewired the send path off the retired agent bus
 * (`api.messages.sendUnified` / `/api/v1/messages/*`) onto the Hub's thread
 * primitives (`commHubStore` -> `/api/v1/threads/*`) — the SAME store
 * HubComposer.vue posts through. These tests mock `@/services/api`'s
 * `threads` namespace directly (mirrors HubComposer.spec.js) rather than the
 * global `tests/setup.js` mock, which only covers the (now-unused) `messages`
 * bus namespace.
 *
 * Edition scope: CE
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const listMock = vi.fn()
const createMock = vi.fn()
const postMock = vi.fn()
const searchMock = vi.fn()
const showToastMock = vi.fn()

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: (...args) => listMock(...args),
      create: (...args) => createMock(...args),
      post: (...args) => postMock(...args),
      search: (...args) => searchMock(...args),
    },
  },
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

import MessageComposer from '@/components/projects/MessageComposer.vue'

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------

function mountComposer(propsData = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)

  const props = {
    projectId: 'proj-solo',
    chainMode: false,
    conductorAgentId: '',
    chainRunId: '',
    orchestratorAgentId: 'agent-orch',
    ...propsData,
  }

  return mount(MessageComposer, {
    global: { plugins: [pinia] },
    props,
  })
}

async function setMessage(wrapper, text) {
  wrapper.vm.messageText = text
  await wrapper.vm.$nextTick()
}

const boundThread = (overrides = {}) => ({
  thread_id: 'thread-bound',
  project_id: 'proj-solo',
  subject: '(project comms)',
  status: 'open',
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

describe('MessageComposer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listMock.mockResolvedValue({ data: { threads: [] } })
    createMock.mockResolvedValue({ data: boundThread() })
    postMock.mockResolvedValue({ data: { message_id: 'msg-new' } })
    searchMock.mockResolvedValue({ data: { threads: [] } })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  // 1. SOLO — orchestrator recipient (default), one existing bound thread
  it('SOLO: posts a directed, requires_action message to the project bound thread', async () => {
    listMock.mockResolvedValue({ data: { threads: [boundThread()] } })

    const wrapper = mountComposer({ projectId: 'proj-solo', chainMode: false })
    await setMessage(wrapper, 'hello orchestrator')

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(createMock).not.toHaveBeenCalled()
    expect(postMock).toHaveBeenCalledTimes(1)
    const [threadId, body] = postMock.mock.calls[0]
    expect(threadId).toBe('thread-bound')
    expect(body.content).toBe('hello orchestrator')
    expect(body.to_participant).toBe('agent-orch')
    expect(body.requires_action).toBe(true)
  })

  // 2. SOLO — broadcast: no to_participant, not requires_action
  it('SOLO: broadcasts to the project bound thread with no to_participant', async () => {
    listMock.mockResolvedValue({ data: { threads: [boundThread()] } })

    const wrapper = mountComposer({ projectId: 'proj-solo', chainMode: false })
    await setMessage(wrapper, 'hello everyone')
    wrapper.vm.selectedRecipient = 'broadcast'
    await wrapper.vm.$nextTick()

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(postMock).toHaveBeenCalledTimes(1)
    const [threadId, body] = postMock.mock.calls[0]
    expect(threadId).toBe('thread-bound')
    expect(body.content).toBe('hello everyone')
    expect(body.to_participant).toBeUndefined()
    expect(body.requires_action).toBe(false)
  })

  // 3. SOLO — no bound thread yet: auto-creates one with the marker subject
  it('SOLO: creates the project bound thread (marker subject) when none exists yet', async () => {
    listMock.mockResolvedValue({ data: { threads: [] } })
    createMock.mockResolvedValue({ data: boundThread({ thread_id: 'thread-fresh' }) })

    const wrapper = mountComposer({ projectId: 'proj-solo', chainMode: false })
    await setMessage(wrapper, 'first message ever')

    await wrapper.vm.sendMessage()
    await flushPromises()

    // EXACT match on purpose, and the exactness is the assertion: this create must
    // carry project_id and NOT product_id. The server derives a bound thread's
    // product from THAT PROJECT, "regardless of which tab the caller happens to be
    // viewing", so naming a product here would override a correct binding with
    // whatever tab happened to be open.
    //
    // Said out loud because FE-9588 just taught the opposite lesson one file over:
    // NewThreadDialog now DOES send the viewed product, since a general thread has
    // no project to derive from. Anyone tidying the two paths into consistency will
    // add product_id here and get a red with no explanation — this is the
    // explanation. The rule is per-path, not global.
    expect(createMock).toHaveBeenCalledWith({ project_id: 'proj-solo', subject: '(project comms)' })
    expect(postMock).toHaveBeenCalledTimes(1)
    expect(postMock.mock.calls[0][0]).toBe('thread-fresh')
  })

  // 4. SOLO — several bound threads: prefers the marker-subject one
  it('SOLO: prefers the marker-subject thread when several bound threads exist', async () => {
    listMock.mockResolvedValue({
      data: {
        threads: [
          boundThread({ thread_id: 'thread-organic', subject: 'Some organic subject', created_at: '2025-01-01T00:00:00Z' }),
          boundThread({ thread_id: 'thread-marked', subject: '(project comms)', created_at: '2025-06-01T00:00:00Z' }),
        ],
      },
    })

    const wrapper = mountComposer({ projectId: 'proj-solo', chainMode: false })
    await setMessage(wrapper, 'pick the marked one')
    wrapper.vm.selectedRecipient = 'broadcast'
    await wrapper.vm.$nextTick()

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(postMock.mock.calls[0][0]).toBe('thread-marked')
  })

  // 5. SOLO — no orchestrator resolvable: errors, does not post
  it('SOLO: shows an error and does not post when no orchestrator agent_id is available', async () => {
    listMock.mockResolvedValue({ data: { threads: [boundThread()] } })

    const wrapper = mountComposer({ projectId: 'proj-solo', chainMode: false, orchestratorAgentId: '' })
    await setMessage(wrapper, 'nobody home')

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(postMock).not.toHaveBeenCalled()
    expect(showToastMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error', message: expect.stringContaining('No orchestrator') }),
    )
  })

  // 6. CHAIN — orchestrator recipient rerouted to the conductor's coordination thread
  it('CHAIN: reroutes orchestrator message to the conductor coordination thread', async () => {
    searchMock.mockResolvedValue({
      data: { threads: [{ thread_id: 'thread-conductor', subject: 'Chain run run-123 coordination hub' }] },
    })

    const wrapper = mountComposer({
      projectId: 'proj-member',
      chainMode: true,
      conductorAgentId: 'agent-conductor',
      chainRunId: 'run-123',
    })
    await setMessage(wrapper, 'chain directive')

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(searchMock).toHaveBeenCalledWith({ query: 'run-123' })
    expect(listMock).not.toHaveBeenCalled()
    expect(postMock).toHaveBeenCalledTimes(1)
    const [threadId, body] = postMock.mock.calls[0]
    expect(threadId).toBe('thread-conductor')
    expect(body.to_participant).toBe('agent-conductor')
    expect(body.requires_action).toBe(true)
    expect(body.content).toBe('chain directive')
  })

  // 7. CHAIN — broadcast stays scoped to the active project, NOT routed to the conductor
  it('CHAIN: broadcast stays scoped to the active project bound thread, not the conductor', async () => {
    listMock.mockResolvedValue({ data: { threads: [boundThread({ project_id: 'proj-member' })] } })

    const wrapper = mountComposer({
      projectId: 'proj-member',
      chainMode: true,
      conductorAgentId: 'agent-conductor',
      chainRunId: 'run-123',
    })
    await setMessage(wrapper, 'broadcast to members')
    wrapper.vm.selectedRecipient = 'broadcast'
    await wrapper.vm.$nextTick()

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(searchMock).not.toHaveBeenCalled()
    expect(postMock).toHaveBeenCalledTimes(1)
    expect(postMock.mock.calls[0][1].to_participant).toBeUndefined()
  })

  // 8. CHAIN — empty conductorAgentId falls back to the project orchestrator path
  it('CHAIN: falls back to the project orchestrator when conductorAgentId is empty', async () => {
    listMock.mockResolvedValue({ data: { threads: [boundThread({ project_id: 'proj-member' })] } })

    const wrapper = mountComposer({
      projectId: 'proj-member',
      chainMode: true,
      conductorAgentId: '',
      chainRunId: 'run-123',
      orchestratorAgentId: 'agent-local-orch',
    })
    await setMessage(wrapper, 'fallback message')

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(searchMock).not.toHaveBeenCalled()
    expect(postMock).toHaveBeenCalledTimes(1)
    expect(postMock.mock.calls[0][1].to_participant).toBe('agent-local-orch')
  })

  // 9. CHAIN — conductor hasn't created its coordination thread yet
  it('CHAIN: warns and does not post when the conductor coordination thread is not found', async () => {
    searchMock.mockResolvedValue({ data: { threads: [] } })

    const wrapper = mountComposer({
      projectId: 'proj-member',
      chainMode: true,
      conductorAgentId: 'agent-conductor',
      chainRunId: 'run-999',
    })
    await setMessage(wrapper, 'too early')

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(postMock).not.toHaveBeenCalled()
    expect(showToastMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning', message: expect.stringContaining("hasn't set up") }),
    )
  })

  // Guard: empty message must not touch the Hub at all
  it('does not call the Hub when message text is empty', async () => {
    const wrapper = mountComposer({ projectId: 'proj-solo' })

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(listMock).not.toHaveBeenCalled()
    expect(postMock).not.toHaveBeenCalled()
  })

  // Post-send: clears messageText and emits 'message-sent'
  it('clears messageText and emits message-sent after a successful send', async () => {
    listMock.mockResolvedValue({ data: { threads: [boundThread()] } })

    const wrapper = mountComposer({ projectId: 'proj-solo' })
    await setMessage(wrapper, 'clear me')

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(wrapper.vm.messageText).toBe('')
    expect(wrapper.emitted('message-sent')).toBeTruthy()
  })
})
