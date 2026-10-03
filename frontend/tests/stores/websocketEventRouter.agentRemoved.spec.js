import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  EVENT_MAP,
  routeWebsocketEvent,
  defaultShouldRoute,
} from '@/stores/websocketEventRouter'
import { useProjectTabsStore } from '@/stores/projectTabs'
import { useUserStore } from '@/stores/user'

// BE-6123: agent:removed drops a hard-deleted never-run orchestrator fixture
// live. It routes to agentJobsStore.removeJob and is project-scoped (filtered
// like agent:created) so a removal for another project never touches the store.
describe('websocketEventRouter - agent:removed (BE-6123)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const userStore = useUserStore()
    if (!userStore.currentUser) userStore.currentUser = {}
    userStore.currentUser.tenant_key = 'test-tenant'
  })

  it('routes agent:removed to removeJob with agent_id', async () => {
    const agentJobsStore = { removeJob: vi.fn() }
    const storeRegistry = { agentJobs: () => agentJobsStore, agents: () => agentJobsStore }

    const routed = await routeWebsocketEvent(
      {
        type: 'agent:removed',
        data: {
          project_id: 'project-1',
          agent_id: 'agent-abc',
          execution_id: 'exec-1',
          job_id: 'job-1',
          tenant_key: 'test-tenant',
        },
      },
      { eventMap: EVENT_MAP, storeRegistry },
    )

    expect(routed).toBe(true)
    expect(agentJobsStore.removeJob).toHaveBeenCalledTimes(1)
    expect(agentJobsStore.removeJob).toHaveBeenCalledWith('agent-abc')
  })

  it('routes agent:removed when project_id matches the current project', async () => {
    useProjectTabsStore().setCurrentProject({ id: 'project-1' })
    const agentJobsStore = { removeJob: vi.fn() }
    const storeRegistry = { agentJobs: () => agentJobsStore, agents: () => agentJobsStore }

    await routeWebsocketEvent(
      {
        type: 'agent:removed',
        data: { project_id: 'project-1', agent_id: 'agent-abc', tenant_key: 'test-tenant' },
      },
      { eventMap: EVENT_MAP, storeRegistry, shouldRoute: defaultShouldRoute },
    )

    expect(agentJobsStore.removeJob).toHaveBeenCalledTimes(1)
  })

  it('drops agent:removed when project_id does NOT match (project-scoped)', async () => {
    useProjectTabsStore().setCurrentProject({ id: 'project-1' })
    const agentJobsStore = { removeJob: vi.fn() }
    const storeRegistry = { agentJobs: () => agentJobsStore, agents: () => agentJobsStore }

    const routed = await routeWebsocketEvent(
      {
        type: 'agent:removed',
        data: { project_id: 'project-2', agent_id: 'agent-abc', tenant_key: 'test-tenant' },
      },
      { eventMap: EVENT_MAP, storeRegistry, shouldRoute: defaultShouldRoute },
    )

    expect(routed).toBe(false)
    expect(agentJobsStore.removeJob).not.toHaveBeenCalled()
  })
})
