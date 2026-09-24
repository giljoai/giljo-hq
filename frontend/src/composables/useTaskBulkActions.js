import { ref, computed, watch } from 'vue'
import { useTaskStore } from '@/stores/tasks'
import { useToast } from '@/composables/useToast'
import { useBulkSelection, runBulk, describeBulkResult, bulkResultType } from '@/composables/useBulkSelection'
import { isHandoverRow } from '@/utils/taxonomyBadge'

export const PENDING_HANDOVER_REASON = 'pending handover (nobody has read it yet)'

export function useTaskBulkActions({ visibleTasks, filterKeys }) {
  const taskStore = useTaskStore()
  const { showToast } = useToast()
  const bulk = useBulkSelection()
  const busy = ref(false)
  const pageCount = ref(0)

  watch(filterKeys, () => bulk.clear(), { deep: true })

  const canArchive = computed(() => bulk.selectedItems.value.some((t) => !t.hidden))
  const canUnarchive = computed(() => bulk.selectedItems.value.some((t) => t.hidden))

  function onSelectedIds(ids) {
    bulk.setSelectedIds(ids, visibleTasks.value)
  }

  function selectAllMatching() {
    bulk.selectAll(visibleTasks.value)
  }

  async function run(verb, rows, action, opts) {
    busy.value = true
    try {
      const result = await runBulk(rows, action, opts)
      const leftover = new Set([...result.skipped, ...result.failed].map(({ row }) => row.id))
      const remaining = bulk.selectedItems.value.filter((t) => leftover.has(t.id) || !rows.includes(t))
      bulk.setSelectedIds(
        remaining.map((t) => t.id),
        remaining,
      )
      showToast({ message: describeBulkResult(verb, result), type: bulkResultType(result) })
      return result
    } finally {
      busy.value = false
    }
  }

  function archiveSelected() {
    const rows = bulk.selectedItems.value.filter((t) => !t.hidden)
    return run('archived', rows, (t) => taskStore.updateTask(t.id, { hidden: true }), {
      skipReason: (t) => (isHandoverRow(t) && t.status === 'pending' ? PENDING_HANDOVER_REASON : null),
    })
  }

  function unarchiveSelected() {
    const rows = bulk.selectedItems.value.filter((t) => t.hidden)
    return run('unarchived', rows, (t) => taskStore.updateTask(t.id, { hidden: false }))
  }

  function deleteSelected() {
    return run('deleted', bulk.selectedItems.value.slice(), (t) => taskStore.deleteTask(t.id))
  }

  return {
    bulk,
    busy,
    pageCount,
    canArchive,
    canUnarchive,
    onSelectedIds,
    selectAllMatching,
    archiveSelected,
    unarchiveSelected,
    deleteSelected,
  }
}
