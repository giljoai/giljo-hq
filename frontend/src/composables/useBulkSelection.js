import { ref, computed } from 'vue'

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

export async function runBulk(rows, action, { skipReason } = {}) {
  const done = []
  const skipped = []
  const failed = []
  for (const row of rows || []) {
    const reason = skipReason ? skipReason(row) : null
    if (reason) {
      skipped.push({ row, reason })
      continue
    }
    try {
      await action(row)
      done.push(row)
    } catch (error) {
      failed.push({ row, reason: serverReason(error) })
    }
  }
  return { done, skipped, failed }
}

function serverReason(error) {
  const data = error?.response?.data
  const detail = data?.detail ?? data?.message
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message
  return 'the server refused it'
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
