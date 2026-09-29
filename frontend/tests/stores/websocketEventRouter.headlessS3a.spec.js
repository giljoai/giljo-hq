/**
 * Headless S3a — routes for the dead WS emissions D4, D11, D14, D15.
 *
 * D4  job:mission_updated            -> agentJobs.handleMissionLengthUpdated (existing-only)
 * D11 project:memory_updated         -> window CustomEvent (dispatch-only; S3c owns the consumer)
 * (D12 orchestrator:handover_initiated retired with the Hand over row action: no emitter remains.)
 * D14 project:launched               -> projectState.setLaunched + projects.debouncedRefreshList
 * D15 projects:bulk:deactivated      -> projects.debouncedRefreshList
 *
 * Edition Scope: CE
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { EVENT_MAP, routeWebsocketEvent } from '@/stores/websocketEventRouter'

const { mockList } = vi.hoisted(() => ({ mockList: vi.fn() }))

vi.mock('@/services/api', () => ({
  api: { projects: { list: mockList, get: vi.fn() } },
  default: { projects: { list: mockList, get: vi.fn() } },
}))

vi.mock('@/stores/products', () => ({
  useProductStore: () => ({ currentProductId: null }),
}))

describe('websocketEventRouter — Headless S3a dead-emission routes', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('D4 job:mission_updated', () => {
    it('routes to agentJobs.handleMissionLengthUpdated', async () => {
      const agentJobsStore = { handleMissionLengthUpdated: vi.fn() }
      const storeRegistry = { agentJobs: () => agentJobsStore }

      await routeWebsocketEvent(
        {
          type: 'job:mission_updated',
          data: { job_id: 'job-1', job_type: 'orchestrator', mission_length: 42, project_id: 'proj-1' },
        },
        { eventMap: EVENT_MAP, storeRegistry },
      )

      expect(agentJobsStore.handleMissionLengthUpdated).toHaveBeenCalledTimes(1)
      expect(agentJobsStore.handleMissionLengthUpdated).toHaveBeenCalledWith(
        expect.objectContaining({ job_id: 'job-1', mission_length: 42 }),
      )
    })

    it('does NOT route through handleUpdated (its confusably-named neighbour agent:mission_updated does)', async () => {
      const agentJobsStore = { handleMissionLengthUpdated: vi.fn(), handleUpdated: vi.fn() }
      const storeRegistry = { agentJobs: () => agentJobsStore }

      await routeWebsocketEvent(
        { type: 'job:mission_updated', data: { job_id: 'job-1', mission_length: 10 } },
        { eventMap: EVENT_MAP, storeRegistry },
      )

      expect(agentJobsStore.handleUpdated).not.toHaveBeenCalled()
    })
  })

  describe('D11 project:memory_updated', () => {
    it('dispatches a window CustomEvent (no store mutation — S3c owns the consumer)', async () => {
      const listener = vi.fn()
      window.addEventListener('project:memory_updated', listener)
      try {
        await routeWebsocketEvent(
          {
            type: 'project:memory_updated',
            data: { project_id: 'proj-1', project_name: 'Alpha', sequence_number: 3 },
          },
          { eventMap: EVENT_MAP, storeRegistry: {} },
        )

        expect(listener).toHaveBeenCalledTimes(1)
        expect(listener.mock.calls[0][0].detail).toEqual(
          expect.objectContaining({ project_id: 'proj-1', sequence_number: 3 }),
        )
      } finally {
        window.removeEventListener('project:memory_updated', listener)
      }
    })
  })

  describe('D14 project:launched and D15 projects:bulk:deactivated', () => {
    beforeEach(() => {
      vi.useFakeTimers()
      mockList.mockReset()
      mockList.mockResolvedValue({ data: [], headers: {} })
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('project:launched debounce-refreshes the projects list', async () => {
      await routeWebsocketEvent(
        { type: 'project:launched', data: { project_id: 'proj-1', staging_status: 'staged' } },
        { eventMap: EVENT_MAP, storeRegistry: {} },
      )

      expect(mockList).not.toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(1000)
      expect(mockList).toHaveBeenCalledTimes(1)
    })

    it('projects:bulk:deactivated debounce-refreshes the projects list', async () => {
      await routeWebsocketEvent(
        { type: 'projects:bulk:deactivated', data: { product_ids: ['prod-a', 'prod-b'] } },
        { eventMap: EVENT_MAP, storeRegistry: {} },
      )

      expect(mockList).not.toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(1000)
      expect(mockList).toHaveBeenCalledTimes(1)
    })

    it('a same-tick burst of project:launched + projects:bulk:deactivated collapses to one refresh', async () => {
      await routeWebsocketEvent(
        { type: 'project:launched', data: { project_id: 'proj-1' } },
        { eventMap: EVENT_MAP, storeRegistry: {} },
      )
      await routeWebsocketEvent(
        { type: 'projects:bulk:deactivated', data: { product_ids: ['prod-a'] } },
        { eventMap: EVENT_MAP, storeRegistry: {} },
      )

      await vi.advanceTimersByTimeAsync(1000)
      expect(mockList).toHaveBeenCalledTimes(1)
    })
  })
})
