import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref, effectScope, nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

import { useProjectStateStore } from '@/stores/projectStateStore'
import { useChainAutoNav, USER_ACTION_GUARD_MS } from './useChainAutoNav'

const stubRouter = () => ({ push: vi.fn(), replace: vi.fn() })

const makeChainCtx = (currentPid) => ({ currentPid, run: { id: 'run-1' } })

describe('useChainAutoNav — FE-6218 live-follow', () => {
  let scope
  let clock

  beforeEach(() => {
    setActivePinia(createPinia())
    scope = effectScope()
    clock = { t: 1_000_000 }
  })

  afterEach(() => scope.stop())

  function build({ chainCtx, projectId, activeTab, router, route }) {
    return scope.run(() =>
      useChainAutoNav({
        chainCtx,
        projectId,
        activeTab,
        router,
        route,
        now: () => clock.t,
      }),
    )
  }

  it('flips to the launch/implement surface when the viewed member reaches staging_complete', async () => {
    const activeTab = ref('jobs')
    build({
      chainCtx: ref(makeChainCtx('p1')),
      projectId: ref('p1'),
      activeTab,
      router: stubRouter(),
      route: { query: { run: 'run-1' } },
    })

    useProjectStateStore().handleStagingComplete({ project_id: 'p1' })
    await nextTick()

    expect(activeTab.value).toBe('launch')
  })

  it('flips to the jobs pane when the viewed member implementation launches', async () => {
    const activeTab = ref('launch')
    build({
      chainCtx: ref(makeChainCtx('p1')),
      projectId: ref('p1'),
      activeTab,
      router: stubRouter(),
      route: { query: {} },
    })

    useProjectStateStore().handleImplementationLaunched({
      project_id: 'p1',
      implementation_launched_at: '2026-06-28T00:00:00Z',
    })
    await nextTick()

    expect(activeTab.value).toBe('jobs')
  })

  it('navigates to the new active member on chain advance, landing on the jobs pane', async () => {
    const activeTab = ref('launch')
    const chainCtx = ref(makeChainCtx('p1'))
    const router = stubRouter()
    build({
      chainCtx,
      projectId: ref('p1'),
      activeTab,
      router,
      route: { query: { run: 'run-1' } },
    })

    chainCtx.value = makeChainCtx('p2')
    await nextTick()

    expect(router.replace).toHaveBeenCalledWith({
      name: 'ProjectLaunch',
      params: { projectId: 'p2' },
      query: { run: 'run-1', tab: 'jobs' },
    })
  })

  it('on advance to the already-viewed member, flips the tab without navigating', async () => {
    const activeTab = ref('launch')
    const chainCtx = ref(makeChainCtx('p1'))
    const router = stubRouter()
    build({
      chainCtx,
      projectId: ref('p2'),
      activeTab,
      router,
      route: { query: { run: 'run-1' } },
    })

    chainCtx.value = makeChainCtx('p2')
    await nextTick()

    expect(activeTab.value).toBe('jobs')
    expect(router.replace).not.toHaveBeenCalled()
  })

  it('ANTI-HIJACK: suppresses the auto-flip within the guard window after a user action', async () => {
    const activeTab = ref('jobs')
    const chainCtx = ref(makeChainCtx('p1'))
    const router = stubRouter()
    const { markUserAction } = build({
      chainCtx,
      projectId: ref('p1'),
      activeTab,
      router,
      route: { query: { run: 'run-1' } },
    })

    markUserAction()

    useProjectStateStore().handleStagingComplete({ project_id: 'p1' })
    await nextTick()
    expect(activeTab.value).toBe('jobs')

    chainCtx.value = makeChainCtx('p2')
    await nextTick()
    expect(router.replace).not.toHaveBeenCalled()
  })

  it('resumes carrying the user along once the guard window lapses', async () => {
    const activeTab = ref('jobs')
    const { markUserAction } = build({
      chainCtx: ref(makeChainCtx('p1')),
      projectId: ref('p1'),
      activeTab,
      router: stubRouter(),
      route: { query: { run: 'run-1' } },
    })

    markUserAction()
    clock.t += USER_ACTION_GUARD_MS + 1

    useProjectStateStore().handleStagingComplete({ project_id: 'p1' })
    await nextTick()
    expect(activeTab.value).toBe('launch')
  })

  describe('SOLO headless-run follow (chainCtx null) — FE-6228', () => {
    it('flips to the launch surface on staging_complete (no chain, no ?run=)', async () => {
      const activeTab = ref('jobs')
      const router = stubRouter()
      build({
        chainCtx: ref(null),
        projectId: ref('solo-pid'),
        activeTab,
        router,
        route: { query: {} },
      })

      useProjectStateStore().handleStagingComplete({ project_id: 'solo-pid' })
      await nextTick()

      expect(activeTab.value).toBe('launch')
      expect(router.replace).not.toHaveBeenCalled()
    })

    it('flips to the jobs pane on implementation_launched (no chain, no ?run=)', async () => {
      const activeTab = ref('launch')
      const router = stubRouter()
      build({
        chainCtx: ref(null),
        projectId: ref('solo-pid'),
        activeTab,
        router,
        route: { query: {} },
      })

      useProjectStateStore().handleImplementationLaunched({
        project_id: 'solo-pid',
        implementation_launched_at: '2026-06-28T00:00:00Z',
      })
      await nextTick()

      expect(activeTab.value).toBe('jobs')
      expect(router.replace).not.toHaveBeenCalled()
    })

    it('ANTI-HIJACK in solo: the same-project flip is suppressed inside the guard window', async () => {
      const activeTab = ref('jobs')
      const { markUserAction } = build({
        chainCtx: ref(null),
        projectId: ref('solo-pid'),
        activeTab,
        router: stubRouter(),
        route: { query: {} },
      })

      markUserAction()

      useProjectStateStore().handleStagingComplete({ project_id: 'solo-pid' })
      await nextTick()
      expect(activeTab.value).toBe('jobs')
    })

    it('resumes carrying the solo user once the guard window lapses', async () => {
      const activeTab = ref('jobs')
      const { markUserAction } = build({
        chainCtx: ref(null),
        projectId: ref('solo-pid'),
        activeTab,
        router: stubRouter(),
        route: { query: {} },
      })

      markUserAction()
      clock.t += USER_ACTION_GUARD_MS + 1

      useProjectStateStore().handleStagingComplete({ project_id: 'solo-pid' })
      await nextTick()
      expect(activeTab.value).toBe('launch')
    })

    it('cross-project advance watcher stays INERT in solo (no router.replace ever)', async () => {
      const activeTab = ref('launch')
      const router = stubRouter()
      build({
        chainCtx: ref(null),
        projectId: ref('solo-pid'),
        activeTab,
        router,
        route: { query: { run: 'run-1' } },
      })

      const projectState = useProjectStateStore()
      projectState.handleStagingComplete({ project_id: 'solo-pid' })
      projectState.handleImplementationLaunched({ project_id: 'solo-pid', implementation_launched_at: 'x' })
      await nextTick()

      expect(router.replace).not.toHaveBeenCalled()
      expect(router.push).not.toHaveBeenCalled()
    })
  })

  describe('TSK-6254 / BE-9111: payload.source gates the implementation_launched flip', () => {
    it('source="mcp" -> follows the headless drive (flips to jobs)', async () => {
      const activeTab = ref('launch')
      build({
        chainCtx: ref(makeChainCtx('p1')),
        projectId: ref('p1'),
        activeTab,
        router: stubRouter(),
        route: { query: { run: 'run-1' } },
      })

      useProjectStateStore().handleImplementationLaunched({
        project_id: 'p1',
        implementation_launched_at: '2026-06-28T00:00:00Z',
        source: 'mcp',
      })
      await nextTick()

      expect(activeTab.value).toBe('jobs')
    })

    it('source="ui" + suppression window OPEN (own click) -> does NOT flip', async () => {
      const activeTab = ref('launch')
      const { markUserAction } = build({
        chainCtx: ref(makeChainCtx('p1')),
        projectId: ref('p1'),
        activeTab,
        router: stubRouter(),
        route: { query: { run: 'run-1' } },
      })

      markUserAction()

      useProjectStateStore().handleImplementationLaunched({
        project_id: 'p1',
        implementation_launched_at: '2026-06-28T00:00:00Z',
        source: 'ui',
      })
      await nextTick()

      expect(activeTab.value).toBe('launch')
    })

    it('source="ui" + window EXPIRED (other window/surface) -> flips to jobs', async () => {
      const activeTab = ref('launch')
      build({
        chainCtx: ref(makeChainCtx('p1')),
        projectId: ref('p1'),
        activeTab,
        router: stubRouter(),
        route: { query: { run: 'run-1' } },
      })

      useProjectStateStore().handleImplementationLaunched({
        project_id: 'p1',
        implementation_launched_at: '2026-06-28T00:00:00Z',
        source: 'ui',
      })
      await nextTick()

      expect(activeTab.value).toBe('jobs')
    })

    it('source absent -> falls back to the anti-hijack window (suppressed within it)', async () => {
      const activeTab = ref('launch')
      const { markUserAction } = build({
        chainCtx: ref(makeChainCtx('p1')),
        projectId: ref('p1'),
        activeTab,
        router: stubRouter(),
        route: { query: { run: 'run-1' } },
      })

      markUserAction()

      useProjectStateStore().handleImplementationLaunched({
        project_id: 'p1',
        implementation_launched_at: '2026-06-28T00:00:00Z',
      })
      await nextTick()

      expect(activeTab.value).toBe('launch')
    })
  })

  it('RULE-3 guard: advance does NOT cross-navigate when route.query.run is absent', async () => {
    const activeTab = ref('launch')
    const chainCtx = ref(makeChainCtx('p1'))
    const router = stubRouter()
    build({
      chainCtx,
      projectId: ref('p1'),
      activeTab,
      router,
      route: { query: {} },
    })

    chainCtx.value = makeChainCtx('p2')
    await nextTick()

    expect(router.replace).not.toHaveBeenCalled()
  })

  it('ignores a sibling member being driven (only the VIEWED member flips the pane)', async () => {
    const activeTab = ref('jobs')
    build({
      chainCtx: ref(makeChainCtx('p1')),
      projectId: ref('p1'),
      activeTab,
      router: stubRouter(),
      route: { query: { run: 'run-1' } },
    })

    useProjectStateStore().handleStagingComplete({ project_id: 'p2' })
    await nextTick()

    expect(activeTab.value).toBe('jobs')
  })
})
