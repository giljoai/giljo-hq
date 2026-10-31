import { describe, it, expect, vi } from 'vitest'
import { useBulkSelection, runBulkBatch, describeBulkResult, bulkResultType } from './useBulkSelection'

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

describe('runBulkBatch', () => {
  it('sends every non-skipped row in ONE request and maps the per-id result back to rows', async () => {
    const send = vi.fn(async () => ({
      done: ['a'],
      skipped: [{ id: 'c', reason: 'not found' }],
      failed: [],
    }))
    const result = await runBulkBatch(rows, send, { skipReason: (r) => (r.id === 'b' ? 'pending handover' : null) })

    expect(send).toHaveBeenCalledTimes(1)
    expect(send).toHaveBeenCalledWith(['a', 'c'])
    expect(result.done).toEqual([rows[0]])
    expect(result.skipped).toEqual([
      { row: rows[1], reason: 'pending handover' },
      { row: rows[2], reason: 'not found' },
    ])
    expect(result.failed).toEqual([])
  })

  it('a rejected request fails every row it carried, with the server reason', async () => {
    const error = new Error('409')
    error.response = { data: { error_code: 'VALIDATIONERROR', message: 'Nope' } }
    const result = await runBulkBatch(rows, vi.fn().mockRejectedValue(error))
    expect(result.done).toEqual([])
    expect(result.failed.map((f) => f.reason)).toEqual(['Nope', 'Nope', 'Nope'])
  })

  it('sends nothing when every row is skipped up front', async () => {
    const send = vi.fn()
    const result = await runBulkBatch(rows, send, { skipReason: () => 'no' })
    expect(send).not.toHaveBeenCalled()
    expect(result.skipped).toHaveLength(3)
  })

  it('splits past the 500-id cap into more than one request', async () => {
    const many = Array.from({ length: 501 }, (_, i) => ({ id: `r${i}` }))
    const send = vi.fn(async (ids) => ({ done: ids, skipped: [], failed: [] }))
    const result = await runBulkBatch(many, send)
    expect(send.mock.calls.map(([ids]) => ids.length)).toEqual([500, 1])
    expect(result.done).toHaveLength(501)
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
