import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/api', () => {
  const api = {
    agentJobs: { list: vi.fn(), mission: vi.fn(), getMission: vi.fn() },
    threads: { markRead: vi.fn(), history: vi.fn(), threadPostAttention: vi.fn() },
    approvals: { listPending: vi.fn() },
  }
  return { default: api, api }
})

import api from '@/services/api'
import { useAgentJobsStore } from './agentJobsStore'
import { useCommHubStore } from './commHubStore'
import { useApprovalsStore } from './useApprovalsStore'
import { AGENT_EVENT_ROUTES } from './eventRoutes/agentEventRoutes'

const boom = () => Promise.reject(new Error('read failed'))
const warnedWith = (spy, text) => spy.mock.calls.some((args) => args.some((a) => String(a?.message ?? a).includes(text)))

describe('background failures are warned, not hidden', () => {
  let warn
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'debug').mockImplementation(() => {})
  })
  afterEach(() => vi.useRealTimers())

  it('the messages-waiting refresh', async () => {
    vi.useFakeTimers()
    api.agentJobs.list.mockImplementation(boom)
    useAgentJobsStore().refreshMessagesWaitingCounts('p1')
    await vi.advanceTimersByTimeAsync(3500)
    expect(warnedWith(warn, 'read failed')).toBe(true)
  })

  it('a thread read watermark that could not be written', async () => {
    api.threads.markRead.mockImplementation(boom)
    useCommHubStore().selectThread('t1')
    await vi.waitFor(() => expect(warnedWith(warn, 'read failed')).toBe(true))
  })

  it('a thread history top-up', async () => {
    api.threads.history.mockImplementation(boom)
    await useCommHubStore().hydrateThreadMessages('t1')
    expect(warnedWith(warn, 'read failed')).toBe(true)
  })

  it('an approvals refresh riding an agent status event', async () => {
    useApprovalsStore().handleStatusEvent = vi.fn(boom)
    await AGENT_EVENT_ROUTES['agent:status_changed'].handler({ user_approval_id: 'a1', status: 'awaiting_user' })
    expect(warnedWith(warn, 'read failed')).toBe(true)
  })

  it('a pending-approvals reply of the wrong shape is an error, not an empty inbox', async () => {
    api.approvals.listPending.mockResolvedValue({ data: { rows: [] } })
    const store = useApprovalsStore()
    await expect(store.fetchPending()).rejects.toThrow()
    expect(store.error).toBeTruthy()
  })
})
