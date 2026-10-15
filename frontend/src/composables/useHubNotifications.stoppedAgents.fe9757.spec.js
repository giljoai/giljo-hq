import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick, ref } from 'vue'

import { DECISION_FOCUS, BLOCKED_FOCUS, SILENT_FOCUS } from './useStoppedAgentSignals'

const mockCurrentUser = ref({
  id: 'user-001',
  display_name: 'Sam Rivera',
  tenant_key: 'tenant-abc',
})
vi.mock('@/stores/user', () => ({
  useUserStore: () => ({ currentUser: mockCurrentUser.value }),
}))

const mockRouterPush = vi.fn(() => Promise.resolve())
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockRouterPush }),
}))

vi.mock('@/stores/commHubStore', () => ({
  useCommHubStore: () => ({ threadsById: new Map(), messagesFor: () => [] }),
}))

const mockPopoutScope = vi.hoisted(() => ({ value: 'actionable' }))
vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({
    get popoutScope() {
      return mockPopoutScope.value
    },
  }),
}))

const mockAddNotification = vi.fn()
vi.mock('@/stores/notifications', () => ({
  useNotificationStore: () => ({ addNotification: mockAddNotification }),
}))

const mockMentions = ref([])
const mockDirectedAsks = ref([])
const mockLoaded = ref(true)
vi.mock('./useThreadPostAttention', () => ({
  useThreadPostAttention: () => ({
    mentions: mockMentions,
    directedAsks: mockDirectedAsks,
    loaded: mockLoaded,
    ensureLoaded: vi.fn(() => Promise.resolve()),
    refresh: vi.fn(() => Promise.resolve()),
  }),
}))

const mockYourTurnThreads = ref([])
vi.mock('./useYourTurnThreads', () => ({
  useYourTurnThreads: () => ({
    yourTurnThreads: mockYourTurnThreads,
    ensureThreadsLoaded: vi.fn(() => Promise.resolve()),
  }),
}))

const MIRRORED_TYPES = new Set(['agent:status_changed', 'agent:silent', 'job:progress_update'])

const mockProjects = vi.hoisted(() => new Map())
const mockProjectStates = vi.hoisted(() => new Map())
const mockServerProjects = vi.hoisted(() => new Map())
const mockFetchProject = vi.fn(async (id) => {
  const entity = mockServerProjects.get(id)
  if (!entity) throw new Error('404')
  mockProjects.set(id, entity)
  mockProjectStates.set(id, { implementationLaunched: Boolean(entity.implementation_launched_at) })
  return entity
})
vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    projectById: (id) => mockProjects.get(id) || null,
    fetchProject: mockFetchProject,
  }),
}))
vi.mock('@/stores/projectStateStore', () => ({
  useProjectStateStore: () => ({
    getProjectState: (id) => mockProjectStates.get(id) || null,
  }),
}))

let NotificationConstructorSpy
const closeSpy = vi.fn()

function resetNotificationMock(permission = 'granted') {
  closeSpy.mockClear()
  NotificationConstructorSpy = vi.fn(function MockNotification() {
    this.close = closeSpy
  })
  NotificationConstructorSpy.permission = permission
  NotificationConstructorSpy.requestPermission = vi.fn().mockResolvedValue(permission)
  global.Notification = NotificationConstructorSpy
}

function setHidden(hidden) {
  Object.defineProperty(document, 'hidden', {
    configurable: true,
    get: () => hidden,
  })
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}

async function emitWs(type, payload) {
  window.dispatchEvent(new CustomEvent(type, { detail: payload }))
  await settle()
}

const LAUNCHED_PROJECT = {
  id: 'proj-1',
  name: 'Billing rewrite',
  implementation_launched_at: '2026-10-13T12:00:00Z',
}
const STAGED_PROJECT = {
  id: 'proj-staged',
  name: 'Staged only',
  implementation_launched_at: null,
}

function knowProject(entity) {
  mockProjects.set(entity.id, entity)
  mockProjectStates.set(entity.id, { implementationLaunched: Boolean(entity.implementation_launched_at) })
}

const APPROVAL_EVENT = {
  job_id: 'job-orch',
  project_id: 'proj-1',
  tenant_key: 'tenant-abc',
  agent_display_name: 'orchestrator',
  old_status: 'working',
  status: 'awaiting_user',
  user_approval_id: 'appr-1',
}
const DECIDED_EVENT = {
  ...APPROVAL_EVENT,
  old_status: 'awaiting_user',
  status: 'working',
  decided_option_id: 'opt-a',
}
const LONG_REASON = `BLOCKED: ${'needs the staging database password from the operator '.repeat(6)}`
const BLOCKED_EVENT = {
  job_id: 'job-impl',
  project_id: 'proj-1',
  agent_display_name: 'implementer',
  old_status: 'working',
  status: 'blocked',
  block_reason: LONG_REASON,
}
const UNBLOCKED_EVENT = {
  job_id: 'job-impl',
  project_id: 'proj-1',
  agent_display_name: 'implementer',
  old_status: 'blocked',
  status: 'working',
}
const SILENT_EVENT = {
  job_id: 'job-orch',
  project_id: 'proj-1',
  project_name: 'Billing rewrite',
  tenant_key: 'tenant-abc',
  agent_display_name: 'orchestrator',
  reason: 'Agent stopped communicating',
  execution_id: 'exec-1',
}

async function mountAll() {
  const registry = await import('@/utils/popoutRegistry')
  registry.clearPopoutRegistry()
  const { useHubNotifications } = await import('./useHubNotifications')
  const { useBannerPopoutLifecycle } = await import('./useBannerPopoutLifecycle')
  useHubNotifications()
  useBannerPopoutLifecycle()
  await nextTick()
  return registry
}

function raisedTag() {
  const [, opts] = NotificationConstructorSpy.mock.calls[0]
  return opts.tag
}

const activeListeners = []
const _origAdd = window.addEventListener.bind(window)
const _origRemove = window.removeEventListener.bind(window)

function resetWorld() {
  setActivePinia(createPinia())
  vi.resetModules()
  vi.clearAllMocks()
  resetNotificationMock('granted')
  mockProjects.clear()
  mockProjectStates.clear()
  mockServerProjects.clear()
  mockYourTurnThreads.value = []
  mockMentions.value = []
  mockDirectedAsks.value = []
  mockLoaded.value = true
  mockPopoutScope.value = 'actionable'
  knowProject(LAUNCHED_PROJECT)
  knowProject(STAGED_PROJECT)
  setHidden(true)
  vi.spyOn(window, 'addEventListener').mockImplementation((type, handler, options) => {
    if (type === 'hub:thread_message' || type === 'hub:thread_update' || MIRRORED_TYPES.has(type)) {
      activeListeners.push({ type, handler })
    }
    return _origAdd(type, handler, options)
  })
}

function teardown() {
  for (const { type, handler } of activeListeners) _origRemove(type, handler)
  activeListeners.length = 0
  vi.restoreAllMocks()
  delete global.Notification
  setHidden(false)
}

describe('FE-9757 decision needed: a pending approval pops under Actionable', () => {
  beforeEach(resetWorld)
  afterEach(teardown)

  it('hidden tab, Actionable: ONE popup, titled with the project, tagged per project and per person', async () => {
    await mountAll()

    await emitWs('agent:status_changed', APPROVAL_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
    const [title] = NotificationConstructorSpy.mock.calls[0]
    expect(title).toContain('Billing rewrite')
    expect(raisedTag()).toContain('proj-1')
    expect(raisedTag()).toContain('user-001')
  })

  it('scope ALL also pops it', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:status_changed', APPROVAL_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('scope OFF: nothing', async () => {
    mockPopoutScope.value = 'off'
    await mountAll()

    await emitWs('agent:status_changed', APPROVAL_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a VISIBLE tab gets no popup', async () => {
    setHidden(false)
    await mountAll()

    await emitWs('agent:status_changed', APPROVAL_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('the same approval announced twice raises one popup', async () => {
    await mountAll()

    await emitWs('agent:status_changed', APPROVAL_EVENT)
    await emitWs('agent:status_changed', APPROVAL_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('click opens the project decision surface; nothing navigates before the click', async () => {
    await mountAll()

    await emitWs('agent:status_changed', APPROVAL_EVENT)
    expect(mockRouterPush).not.toHaveBeenCalled()

    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-1', decide: '1' },
    })
  })

  it('deciding the approval closes the popup for real', async () => {
    const registry = await mountAll()

    await emitWs('agent:status_changed', APPROVAL_EVENT)
    const raised = NotificationConstructorSpy.mock.instances[0]
    const tag = raisedTag()
    expect(registry.registeredPopoutTags()).toContain(tag)

    await emitWs('agent:status_changed', DECIDED_EVENT)

    expect(raised.close).toHaveBeenCalledOnce()
    expect(registry.registeredPopoutTags()).not.toContain(tag)
  })

  it('writes NO bell row of its own: the bell path for approvals is unchanged', async () => {
    await mountAll()

    await emitWs('agent:status_changed', APPROVAL_EVENT)

    expect(mockAddNotification).not.toHaveBeenCalled()
  })

  it('an approval from another tenant is ignored', async () => {
    await mountAll()

    await emitWs('agent:status_changed', { ...APPROVAL_EVENT, tenant_key: 'tenant-other' })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })
})

describe('FE-9757 agent blocked: pops under Actionable with the reason, closes when the block clears', () => {
  beforeEach(resetWorld)
  afterEach(teardown)

  it('hidden tab, Actionable: ONE popup whose body is the block reason, truncated', async () => {
    await mountAll()

    await emitWs('agent:status_changed', BLOCKED_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
    const [title, opts] = NotificationConstructorSpy.mock.calls[0]
    expect(title).toContain('implementer')
    expect(opts.body.startsWith('BLOCKED: needs the staging database password')).toBe(true)
    expect(opts.body.length).toBeLessThan(LONG_REASON.length)
    expect(opts.body.length).toBeLessThanOrEqual(120)
    expect(opts.tag).toContain('job-impl')
    expect(opts.tag).toContain('user-001')
  })

  it('scope OFF: nothing', async () => {
    mockPopoutScope.value = 'off'
    await mountAll()

    await emitWs('agent:status_changed', BLOCKED_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a VISIBLE tab gets no popup', async () => {
    setHidden(false)
    await mountAll()

    await emitWs('agent:status_changed', BLOCKED_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('click opens that project on the Jobs board; nothing navigates before the click', async () => {
    await mountAll()

    await emitWs('agent:status_changed', BLOCKED_EVENT)
    expect(mockRouterPush).not.toHaveBeenCalled()

    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-1' },
    })
  })

  it('clearing the block (agent back to working) closes the popup for real', async () => {
    const registry = await mountAll()

    await emitWs('agent:status_changed', BLOCKED_EVENT)
    const raised = NotificationConstructorSpy.mock.instances[0]
    const tag = raisedTag()

    await emitWs('agent:status_changed', UNBLOCKED_EVENT)

    expect(raised.close).toHaveBeenCalledOnce()
    expect(registry.registeredPopoutTags()).not.toContain(tag)
  })

  it('a fresh report from the blocked agent closes the popup', async () => {
    await mountAll()

    await emitWs('agent:status_changed', BLOCKED_EVENT)
    const raised = NotificationConstructorSpy.mock.instances[0]

    await emitWs('job:progress_update', { job_id: 'job-impl', project_id: 'proj-1' })

    expect(raised.close).toHaveBeenCalledOnce()
  })

  it('a report from a DIFFERENT agent leaves the popup up', async () => {
    await mountAll()

    await emitWs('agent:status_changed', BLOCKED_EVENT)
    const raised = NotificationConstructorSpy.mock.instances[0]

    await emitWs('job:progress_update', { job_id: 'job-other', project_id: 'proj-1' })

    expect(raised.close).not.toHaveBeenCalled()
  })

  it('writes NO bell row of its own', async () => {
    await mountAll()

    await emitWs('agent:status_changed', BLOCKED_EVENT)

    expect(mockAddNotification).not.toHaveBeenCalled()
  })
})

describe('FE-9757 orchestrator gone silent: ONLY under All, implementation phase only, one per spell', () => {
  beforeEach(resetWorld)
  afterEach(teardown)

  it('under ACTIONABLE: no popup, even hidden with permission granted', async () => {
    mockPopoutScope.value = 'actionable'
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('under ALL, implementation launched: ONE popup tagged per orchestrator job and per person', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
    const [title, opts] = NotificationConstructorSpy.mock.calls[0]
    expect(title.toLowerCase()).toContain('silent')
    expect(title).toContain('Billing rewrite')
    expect(opts.tag).toContain('job-orch')
    expect(opts.tag).toContain('user-001')
  })

  it('scope OFF: nothing', async () => {
    mockPopoutScope.value = 'off'
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a VISIBLE tab gets no popup', async () => {
    mockPopoutScope.value = 'all'
    setHidden(false)
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a STAGED project waiting for Implement never raises the silent popup, even under All', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:silent', { ...SILENT_EVENT, project_id: 'proj-staged', project_name: 'Staged only' })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a project the stores do not know is read once from the server before deciding', async () => {
    mockPopoutScope.value = 'all'
    mockProjects.clear()
    mockProjectStates.clear()
    mockServerProjects.set('proj-1', LAUNCHED_PROJECT)
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)

    expect(mockFetchProject).toHaveBeenCalledWith('proj-1')
    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('a tab that comes back to front WHILE the project is being read gets no popup', async () => {
    mockPopoutScope.value = 'all'
    mockProjects.clear()
    mockProjectStates.clear()
    mockServerProjects.set('proj-1', LAUNCHED_PROJECT)
    mockFetchProject.mockImplementationOnce(async (id) => {
      setHidden(false)
      const entity = mockServerProjects.get(id)
      mockProjects.set(id, entity)
      mockProjectStates.set(id, { implementationLaunched: true })
      return entity
    })
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)

    expect(mockFetchProject).toHaveBeenCalledWith('proj-1')
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a project that cannot be read at all raises nothing: unknown is treated as not implementing', async () => {
    mockPopoutScope.value = 'all'
    mockProjects.clear()
    mockProjectStates.clear()
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)

    expect(mockFetchProject).toHaveBeenCalledWith('proj-1')
    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('a WORKER agent going silent raises nothing: this popup is for the orchestrator', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:silent', { ...SILENT_EVENT, job_id: 'job-impl', agent_display_name: 'implementer' })

    expect(NotificationConstructorSpy).not.toHaveBeenCalled()
  })

  it('one popup per silent spell: a repeat agent:silent for the same job does not stack', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)
    await emitWs('agent:silent', SILENT_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
  })

  it('the next report from that orchestrator closes the popup for real', async () => {
    mockPopoutScope.value = 'all'
    const registry = await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)
    const raised = NotificationConstructorSpy.mock.instances[0]
    const tag = raisedTag()

    await emitWs('job:progress_update', { job_id: 'job-orch', project_id: 'proj-1' })

    expect(raised.close).toHaveBeenCalledOnce()
    expect(registry.registeredPopoutTags()).not.toContain(tag)
  })

  it('a status event from that job (back to working) also closes it', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)
    const raised = NotificationConstructorSpy.mock.instances[0]

    await emitWs('agent:status_changed', {
      job_id: 'job-orch',
      project_id: 'proj-1',
      agent_display_name: 'orchestrator',
      old_status: 'silent',
      status: 'working',
    })

    expect(raised.close).toHaveBeenCalledOnce()
  })

  it('after the spell ends, a NEW silent spell pops again', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)
    await emitWs('job:progress_update', { job_id: 'job-orch', project_id: 'proj-1' })
    await emitWs('agent:silent', SILENT_EVENT)

    expect(NotificationConstructorSpy).toHaveBeenCalledTimes(2)
  })

  it('click opens that project on the Jobs board', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)
    NotificationConstructorSpy.mock.instances[0].onclick()

    expect(mockRouterPush).toHaveBeenCalledWith({
      name: 'JobsViewport',
      query: { project: 'proj-1' },
    })
  })

  it('writes NO bell row of its own: agentEventRoutes keeps that job', async () => {
    mockPopoutScope.value = 'all'
    await mountAll()

    await emitWs('agent:silent', SILENT_EVENT)

    expect(mockAddNotification).not.toHaveBeenCalled()
  })
})

describe('FE-9757 tags are per person', () => {
  beforeEach(resetWorld)
  afterEach(teardown)

  it('popoutTag carries the user id, so two people never share a tag for the same thing', async () => {
    const { popoutTag } = await import('@/utils/popoutTag')

    const mine = popoutTag(DECISION_FOCUS, 'proj-1', 'user-001')
    const theirs = popoutTag(DECISION_FOCUS, 'proj-1', 'user-002')

    expect(mine).not.toBe(theirs)
    expect(mine).toContain('user-001')
    expect(mine).toContain('proj-1')
    expect(mine).toContain(DECISION_FOCUS)
  })

  it('the existing baton popup carries the user id too, and the lifecycle still closes it', async () => {
    const registry = await mountAll()
    const { popoutTag } = await import('@/utils/popoutTag')
    const { BATON_FOCUS } = await import('@/components/hub/hubThreadRoute')

    mockYourTurnThreads.value = [{ thread_id: 'thread-1', next_action_owner: 'user-001' }]
    await nextTick()
    window.dispatchEvent(
      new CustomEvent('hub:thread_update', {
        detail: { thread_id: 'thread-1', chat_id: 'CHT-0001', next_action_owner: 'user-001' },
      }),
    )

    expect(NotificationConstructorSpy).toHaveBeenCalledOnce()
    const tag = raisedTag()
    expect(tag).toBe(popoutTag(BATON_FOCUS, 'thread-1', 'user-001'))
    expect(registry.registeredPopoutTags()).toContain(tag)

    mockYourTurnThreads.value = []
    await nextTick()

    expect(NotificationConstructorSpy.mock.instances[0].close).toHaveBeenCalledOnce()
  })

  it('the three stopped-agent tags do not collide with each other for one job', async () => {
    const { popoutTag } = await import('@/utils/popoutTag')

    const tags = new Set([
      popoutTag(DECISION_FOCUS, 'job-1', 'user-001'),
      popoutTag(BLOCKED_FOCUS, 'job-1', 'user-001'),
      popoutTag(SILENT_FOCUS, 'job-1', 'user-001'),
    ])

    expect(tags.size).toBe(3)
  })
})
