import { ref, computed } from 'vue'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useBulkSelection() {
  const selection = ref(new Map())
  const allMatching = ref(false)

  const selectedIds = computed(() => Array.from(selection.value.keys()))
  const selectedItems = computed(() => Array.from(selection.value.values()))
  const count = computed(() => selection.value.size)

  function isSelected(id) {
    return selection.value.has(id)
  }

  function toggle(item) {
    if (!item?.id) return
    const next = new Map(selection.value)
    if (next.has(item.id)) next.delete(item.id)
    else next.set(item.id, item)
    selection.value = next
    allMatching.value = false
  }

  function setSelectedIds(ids, rows) {
    const byId = new Map((rows || []).map((r) => [r.id, r]))
    const next = new Map()
    for (const id of ids || []) {
      const row = byId.get(id) || selection.value.get(id)
      if (row) next.set(id, row)
    }
    selection.value = next
    allMatching.value = false
  }

  function selectAll(rows) {
    selection.value = new Map((rows || []).filter((r) => r?.id).map((r) => [r.id, r]))
    allMatching.value = true
  }

  function clear() {
    selection.value = new Map()
    allMatching.value = false
  }

  return {
    selection,
    selectedIds,
    selectedItems,
    count,
    allMatching,
    isSelected,
    toggle,
    setSelectedIds,
    selectAll,
    clear,
  }
}

export const BULK_REQUEST_MAX = 500

export async function runBulkBatch(rows, send, { skipReason } = {}) {
  const done = []
  const skipped = []
  const failed = []
  const toSend = []
  for (const row of rows || []) {
    const reason = skipReason ? skipReason(row) : null
    if (reason) skipped.push({ row, reason })
    else toSend.push(row)
  }
  const byId = new Map(toSend.map((row) => [row.id, row]))
  for (let start = 0; start < toSend.length; start += BULK_REQUEST_MAX) {
    const chunk = toSend.slice(start, start + BULK_REQUEST_MAX)
    try {
      const result = await send(chunk.map((row) => row.id))
      for (const id of result.done || []) done.push(byId.get(id))
      for (const { id, reason } of result.skipped || []) skipped.push({ row: byId.get(id), reason })
      for (const { id, reason } of result.failed || []) failed.push({ row: byId.get(id), reason })
    } catch (error) {
      const reason = parseErrorResponse(error).message
      for (const row of chunk) failed.push({ row, reason })
    }
  }
  return { done, skipped, failed }
}

export function describeBulkResult(verb, { done, skipped, failed }) {
  const parts = [`${done.length} ${verb}`]
  const clause = (label, list) => {
    if (!list.length) return
    const counts = new Map()
    for (const { reason } of list) counts.set(reason, (counts.get(reason) || 0) + 1)
    const reasons = Array.from(counts.entries())
      .map(([reason, n]) => (counts.size > 1 ? `${reason} (${n})` : reason))
      .join('; ')
    parts.push(`${list.length} ${label}: ${reasons}`)
  }
  clause('skipped', skipped)
  clause('failed', failed)
  return parts.join(', ')
}

export function bulkResultType({ done, skipped, failed }) {
  if (!skipped.length && !failed.length) return 'success'
  return done.length ? 'warning' : 'error'
}
