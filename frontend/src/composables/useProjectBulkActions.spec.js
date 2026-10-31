import { describe, it, expect, vi, beforeEach } from 'vitest'
import { computed } from 'vue'
import { useProjectBulkActions, IN_CHAIN_REASON } from './useProjectBulkActions'

const mockBulkClose = vi.fn()
const mockCancelRefresh = vi.fn()
const mockFetchHidden = vi.fn()
const mockFetchAllMatching = vi.fn()
const mockShowToast = vi.fn()

vi.mock('@/stores/projects', () => ({
  useProjectStore: () => ({
    bulkClose: mockBulkClose,
    debouncedRefreshList: { cancel: mockCancelRefresh },
    fetchHiddenProjects: mockFetchHidden,
    fetchAllMatchingProjects: mockFetchAllMatching,
  }),
}))
vi.mock('@/composables/useToast', () => ({
  useToast: () => ({ showToast: mockShowToast }),
}))

const inactive = (id, extra = {}) => ({ id, name: id, taxonomy_alias: id, status: 'inactive', hidden: false, ...extra })

function setup({ inChain = [] } = {}) {
  const reloadProjects = vi.fn().mockResolvedValue(undefined)
  const buildServerParams = vi.fn(() => ({ limit: 25, offset: 50, statuses: ['inactive'], sort: 'created_at' }))
  const api = useProjectBulkActions({
    inChainIds: computed(() => inChain),
    buildServerParams,
    reloadProjects,
    filterKeys: computed(() => []),
  })
  return { api, reloadProjects, buildServerParams }
}

describe('useProjectBulkActions', () => {
  beforeEach(() => {
    for (const m of [mockBulkClose, mockCancelRefresh, mockFetchHidden, mockFetchAllMatching, mockShowToast]) m.mockReset()
    mockBulkClose.mockImplementation(async (_action, ids) => ({ done: ids, skipped: [], failed: [] }))
  })

  it('archive skips a project in an active chain and names why, then reloads the list', async () => {
    const rows = [inactive('p1'), inactive('p2')]
    const { api, reloadProjects } = setup({ inChain: ['p2'] })
    api.onSelectedIds(['p1', 'p2'], rows)

    const result = await api.archiveSelected()

    expect(mockBulkClose.mock.calls).toEqual([['archive', ['p1']]])
    expect(result.skipped).toEqual([{ row: rows[1], reason: IN_CHAIN_REASON }])
    expect(mockShowToast).toHaveBeenCalledWith({ message: `1 archived, 1 skipped: ${IN_CHAIN_REASON}`, type: 'warning' })
    expect(reloadProjects).toHaveBeenCalled()
    expect(mockFetchHidden).toHaveBeenCalled()
  })

  it('archiving 20 selected projects is ONE request, ONE toast and ONE reload', async () => {
    const rows = Array.from({ length: 20 }, (_, i) => inactive(`p${i}`))
    const { api, reloadProjects } = setup()
    api.onSelectedIds(rows.map((r) => r.id), rows)

    await api.archiveSelected()

    expect(mockBulkClose).toHaveBeenCalledTimes(1)
    expect(mockBulkClose.mock.calls[0][1]).toHaveLength(20)
    expect(mockShowToast).toHaveBeenCalledTimes(1)
    expect(mockShowToast).toHaveBeenCalledWith({ message: '20 archived', type: 'success' })
    expect(reloadProjects).toHaveBeenCalledTimes(1)
    expect(mockFetchHidden).toHaveBeenCalledTimes(1)
    expect(mockCancelRefresh).toHaveBeenCalled()
  })

  it('shows what the server skipped, grouped, in the same single toast', async () => {
    mockBulkClose.mockResolvedValue({ done: ['p1'], skipped: [{ id: 'p2', reason: 'not found' }], failed: [] })
    const rows = [inactive('p1', { hidden: true }), inactive('p2', { hidden: true })]
    const { api } = setup()
    api.onSelectedIds(['p1', 'p2'], rows)

    await api.unarchiveSelected()

    expect(mockShowToast).toHaveBeenCalledTimes(1)
    expect(mockShowToast).toHaveBeenCalledWith({ message: '1 unarchived, 1 skipped: not found', type: 'warning' })
  })

  it('delete also leaves chain members alone', async () => {
    const rows = [inactive('p1'), inactive('p2')]
    const { api } = setup({ inChain: ['p1'] })
    api.onSelectedIds(['p1', 'p2'], rows)
    await api.deleteSelected()
    expect(mockBulkClose.mock.calls).toEqual([['delete', ['p2']]])
  })

  it('Chain opens the confirm step with only the eligible rows, and creates nothing itself', () => {
    const rows = [inactive('p1'), inactive('p2'), inactive('p3', { status: 'active' }), inactive('p4')]
    const { api } = setup({ inChain: ['p4'] })
    api.onSelectedIds(['p1', 'p2', 'p3', 'p4'], rows)

    expect(api.chainReady.value).toBe(true)
    expect(api.chainNote.value).toBe('Chain uses 2 of 4: 1 not inactive, 1 already in a chain.')

    api.chainSelected()

    expect(api.showChainDialog.value).toBe(true)
    expect(api.chainRows.value.map((p) => p.id)).toEqual(['p1', 'p2'])
    expect(api.bulk.count.value).toBe(4)
    expect(mockBulkClose).not.toHaveBeenCalled()

    api.onChainStarted()
    expect(api.bulk.count.value).toBe(0)
  })

  it('a chain needs at least 2 eligible projects', () => {
    const { api } = setup()
    api.onSelectedIds(['p1'], [inactive('p1')])
    expect(api.chainReady.value).toBe(false)
    expect(api.chainNote.value).toBe('A chain needs at least 2 inactive projects.')
    api.chainSelected()
    expect(api.showChainDialog.value).toBe(false)
  })

  it('a chain takes at most 10 projects', () => {
    const rows = Array.from({ length: 11 }, (_, i) => inactive(`p${i + 1}`))
    const { api } = setup()
    api.onSelectedIds(rows.map((r) => r.id), rows)
    expect(api.chainReady.value).toBe(false)
    expect(api.chainNote.value).toBe('A chain takes at most 10; untick 1.')
  })

  it('ten eligible projects are allowed (the cap boundary)', () => {
    const rows = Array.from({ length: 10 }, (_, i) => inactive(`p${i + 1}`))
    const { api } = setup()
    api.onSelectedIds(rows.map((r) => r.id), rows)
    expect(api.chainReady.value).toBe(true)
    expect(api.chainNote.value).toBe('')
  })

  it('five eligible projects are allowed', () => {
    const rows = ['p1', 'p2', 'p3', 'p4', 'p5'].map((id) => inactive(id))
    const { api } = setup()
    api.onSelectedIds(rows.map((r) => r.id), rows)
    expect(api.chainReady.value).toBe(true)
    expect(api.chainNote.value).toBe('')
  })

  it('select all matching asks the server for every page of the SAME filters', async () => {
    const all = [inactive('p1'), inactive('p2'), inactive('p3')]
    mockFetchAllMatching.mockResolvedValue(all)
    const { api } = setup()

    await api.selectAllMatching()

    expect(mockFetchAllMatching).toHaveBeenCalledWith({ statuses: ['inactive'], sort: 'created_at' })
    expect(api.bulk.count.value).toBe(3)
    expect(api.bulk.allMatching.value).toBe(true)
  })
})
