import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mockList = vi.fn()
const mockCount = vi.fn()

vi.mock('@/services/api', () => {
  const apiMock = {
    templateProposals: { list: (...a) => mockList(...a), count: (...a) => mockCount(...a) },
  }
  return { api: apiMock, default: apiMock }
})

import { SYSTEM_EVENT_ROUTES } from '@/stores/eventRoutes/systemEventRoutes'
import { useTemplateProposalsStore } from '@/stores/templateProposalsStore'

const two = [
  { id: 'a', target_kind: 'agent_template', template_id: 't1' },
  { id: 'b', target_kind: 'agent_template', template_id: 't2' },
]

describe('template:proposal_decided', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('drops the decided proposal and moves the count without being asked to reload', async () => {
    mockList.mockResolvedValueOnce({ data: { count: 2, proposals: two } })
    const store = useTemplateProposalsStore()
    await store.fetchAll()
    mockList.mockResolvedValueOnce({ data: { count: 1, proposals: [two[1]] } })

    await SYSTEM_EVENT_ROUTES['template:proposal_decided'].handler({ proposal_id: 'a', action: 'apply' })

    expect(store.proposals.map((p) => p.id)).toEqual(['b'])
    expect(store.count).toBe(1)
    expect(Object.keys(store.byTemplateId)).toEqual(['t2'])
  })

  it('moves the count when only the count was loaded (banner without the list)', async () => {
    mockCount.mockResolvedValueOnce({ data: { count: 2 } })
    const store = useTemplateProposalsStore()
    await store.fetchCount()
    mockCount.mockResolvedValueOnce({ data: { count: 1 } })

    await SYSTEM_EVENT_ROUTES['template:proposal_decided'].handler({ proposal_id: 'a', action: 'reject' })

    expect(store.count).toBe(1)
  })

  it('does nothing for a proposal this tab never showed (loaded list, unknown id)', async () => {
    mockList.mockResolvedValueOnce({ data: { count: 2, proposals: two } })
    const store = useTemplateProposalsStore()
    await store.fetchAll()
    mockList.mockClear()

    await SYSTEM_EVENT_ROUTES['template:proposal_decided'].handler({ proposal_id: 'zzz', action: 'apply' })

    expect(mockList).not.toHaveBeenCalled()
    expect(store.count).toBe(2)
  })

  it('ignores a payload without an id', async () => {
    const store = useTemplateProposalsStore()
    await SYSTEM_EVENT_ROUTES['template:proposal_decided'].handler({})
    expect(store.count).toBe(0)
  })
})
