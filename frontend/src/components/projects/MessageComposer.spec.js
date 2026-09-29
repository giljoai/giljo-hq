
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const listMock = vi.fn()
const createMock = vi.fn()
const postMock = vi.fn()
const searchMock = vi.fn()
const chainHubMock = vi.fn()
const showToastMock = vi.fn()

vi.mock('@/services/api', () => ({
  default: {
    threads: {
      list: (...args) => listMock(...args),
      create: (...args) => createMock(...args),
      post: (...args) => postMock(...args),
      search: (...args) => searchMock(...args),
      chainHub: (...args) => chainHubMock(...args),
    },
  },
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: showToastMock }),
}))

import MessageComposer from '@/components/projects/MessageComposer.vue'


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

  it('SOLO: creates the project bound thread (marker subject) when none exists yet', async () => {
    listMock.mockResolvedValue({ data: { threads: [] } })
    createMock.mockResolvedValue({ data: boundThread({ thread_id: 'thread-fresh' }) })

    const wrapper = mountComposer({ projectId: 'proj-solo', chainMode: false })
    await setMessage(wrapper, 'first message ever')

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(createMock).toHaveBeenCalledWith({ project_id: 'proj-solo', subject: '(project comms)' })
    expect(postMock).toHaveBeenCalledTimes(1)
    expect(postMock.mock.calls[0][0]).toBe('thread-fresh')
  })

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

  it('CHAIN: reroutes orchestrator message to the chain hub looked up by run id', async () => {
    chainHubMock.mockResolvedValue({ data: { thread: { thread_id: 'thread-hub', subject: 'Chain: ship it' } } })
    searchMock.mockResolvedValue({
      data: { threads: [{ thread_id: 'thread-decoy', subject: 'Notes on run-123' }] },
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

    expect(chainHubMock).toHaveBeenCalledWith('run-123')
    expect(searchMock).not.toHaveBeenCalled()
    expect(listMock).not.toHaveBeenCalled()
    expect(postMock).toHaveBeenCalledTimes(1)
    const [threadId, body] = postMock.mock.calls[0]
    expect(threadId).toBe('thread-hub')
    expect(body.to_participant).toBe('agent-conductor')
    expect(body.requires_action).toBe(true)
    expect(body.content).toBe('chain directive')
  })

  it('CHAIN: a failed hub lookup shows an error, not "hasn\'t set up", and posts nothing', async () => {
    chainHubMock.mockRejectedValue(new Error('Network Error'))

    const wrapper = mountComposer({
      projectId: 'proj-member',
      chainMode: true,
      conductorAgentId: 'agent-conductor',
      chainRunId: 'run-123',
    })
    await setMessage(wrapper, 'chain directive')

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(postMock).not.toHaveBeenCalled()
    expect(showToastMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' }))
    expect(showToastMock).not.toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining("hasn't set up") }),
    )
  })

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

  it('CHAIN: warns and does not post when the conductor coordination thread is not found', async () => {
    chainHubMock.mockResolvedValue({ data: { thread: null } })

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

  it('does not call the Hub when message text is empty', async () => {
    const wrapper = mountComposer({ projectId: 'proj-solo' })

    await wrapper.vm.sendMessage()
    await flushPromises()

    expect(listMock).not.toHaveBeenCalled()
    expect(postMock).not.toHaveBeenCalled()
  })

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
