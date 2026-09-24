import { describe, it, expect, vi } from 'vitest'
import { useBulkSelection, runBulk, describeBulkResult, bulkResultType } from './useBulkSelection'

const rows = [
  { id: 'a', title: 'A' },
  { id: 'b', title: 'B' },
  { id: 'c', title: 'C' },
]

describe('useBulkSelection', () => {
  it('toggles rows on and off and keeps each row object', () => {
    const s = useBulkSelection()
    s.toggle(rows[0])
    s.toggle(rows[1])
    expect(s.count.value).toBe(2)
    expect(s.selectedItems.value).toEqual([rows[0], rows[1]])
    s.toggle(rows[0])
    expect(s.selectedIds.value).toEqual(['b'])
    expect(s.isSelected('b')).toBe(true)
  })

  it('setSelectedIds keeps rows selected on another page (paging does not drop them)', () => {
    const s = useBulkSelection()
    s.setSelectedIds(['a'], [rows[0]])
    s.setSelectedIds(['a', 'c'], [rows[2]])
    expect(s.selectedItems.value).toEqual([rows[0], rows[2]])
  })

  it('selectAll marks the selection as covering every matching row; any edit clears that flag', () => {
    const s = useBulkSelection()
    s.selectAll(rows)
    expect(s.count.value).toBe(3)
    expect(s.allMatching.value).toBe(true)
    s.toggle(rows[1])
    expect(s.allMatching.value).toBe(false)
    s.clear()
    expect(s.count.value).toBe(0)
  })
})

describe('runBulk', () => {
  it('runs each row one at a time and reports done, skipped and failed separately', async () => {
    const calls = []
    const action = vi.fn(async (row) => {
      calls.push(row.id)
      if (row.id === 'c') {
        const error = new Error('409')
        error.response = { data: { detail: 'Project is active' } }
        throw error
      }
    })
    const result = await runBulk(rows, action, { skipReason: (r) => (r.id === 'b' ? 'pending handover' : null) })

    expect(calls).toEqual(['a', 'c'])
    expect(result.done).toEqual([rows[0]])
    expect(result.skipped).toEqual([{ row: rows[1], reason: 'pending handover' }])
    expect(result.failed).toEqual([{ row: rows[2], reason: 'Project is active' }])
  })

  it('does not stop at the first failure', async () => {
    const action = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValue(undefined)
    const result = await runBulk(rows, action)
    expect(action).toHaveBeenCalledTimes(3)
    expect(result.done).toHaveLength(2)
    expect(result.failed[0].reason).toBe('the server refused it')
  })
})

describe('describeBulkResult', () => {
  it('names what was skipped and why', () => {
    const text = describeBulkResult('archived', {
      done: new Array(12).fill({}),
      skipped: [{ row: {}, reason: 'pending handover' }],
      failed: [],
    })
    expect(text).toBe('12 archived, 1 skipped: pending handover')
  })

  it('groups repeated reasons and counts each when there are several', () => {
    const text = describeBulkResult('deleted', {
      done: [],
      skipped: [
        { row: {}, reason: 'in an active chain' },
        { row: {}, reason: 'in an active chain' },
      ],
      failed: [
        { row: {}, reason: 'Project is active' },
        { row: {}, reason: 'Not found' },
      ],
    })
    expect(text).toBe('0 deleted, 2 skipped: in an active chain, 2 failed: Project is active (1); Not found (1)')
  })

  it('picks the toast type from the outcome', () => {
    expect(bulkResultType({ done: [1], skipped: [], failed: [] })).toBe('success')
    expect(bulkResultType({ done: [1], skipped: [1], failed: [] })).toBe('warning')
    expect(bulkResultType({ done: [], skipped: [], failed: [1] })).toBe('error')
  })
})
