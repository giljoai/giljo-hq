import { ref, computed, watch } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useToast } from '@/composables/useToast'
import { useBulkSelection, runBulk, describeBulkResult, bulkResultType } from '@/composables/useBulkSelection'
import { MAX_SEQUENCE_PROJECTS } from '@/utils/sequenceOrder'

const MIN_CHAIN_PROJECTS = 2

export const IN_CHAIN_REASON = 'in an active chain (use Deactivate Chain first)'

const isInactive = (p) => (p.status || 'inactive') === 'inactive'

export function useProjectBulkActions({ inChainIds, buildServerParams, reloadProjects, filterKeys }) {
  const projectStore = useProjectStore()
  const { showToast } = useToast()
  const bulk = useBulkSelection()
  const busy = ref(false)

  watch(filterKeys, () => bulk.clear(), { deep: true })

  const showChainDialog = ref(false)
  const chainRows = ref([])

  const inChain = (p) => inChainIds.value.includes(p.id)
  const inChainSkip = (p) => (inChain(p) ? IN_CHAIN_REASON : null)

  const canArchive = computed(() => bulk.selectedItems.value.some((p) => !p.hidden))
  const canUnarchive = computed(() => bulk.selectedItems.value.some((p) => p.hidden))

  const chainEligibleRows = computed(() => bulk.selectedItems.value.filter((p) => isInactive(p) && !inChain(p)))
  const chainReady = computed(() => {
    const n = chainEligibleRows.value.length
    return n >= MIN_CHAIN_PROJECTS && n <= MAX_SEQUENCE_PROJECTS
  })
  const chainNote = computed(() => {
    const rows = bulk.selectedItems.value
    const n = chainEligibleRows.value.length
    const alreadyChained = rows.filter(inChain).length
    const notInactive = rows.filter((p) => !inChain(p) && !isInactive(p)).length
    const why = [
      notInactive ? `${notInactive} not inactive` : '',
      alreadyChained ? `${alreadyChained} already in a chain` : '',
    ]
      .filter(Boolean)
      .join(', ')
    const parts = []
    if (why) parts.push(`Chain uses ${n} of ${rows.length}: ${why}.`)
    if (n > MAX_SEQUENCE_PROJECTS) parts.push(`A chain takes at most ${MAX_SEQUENCE_PROJECTS}; untick ${n - MAX_SEQUENCE_PROJECTS}.`)
    else if (n === 1 && rows.length > 0) parts.push('A chain needs at least 2 inactive projects.')
    return parts.join(' ')
  })

  function onSelectedIds(ids, pageRows) {
    bulk.setSelectedIds(ids, pageRows)
  }

  async function selectAllMatching() {
    busy.value = true
    try {
      const { limit: _limit, offset: _offset, ...params } = buildServerParams()
      bulk.selectAll(await projectStore.fetchAllMatchingProjects(params))
    } catch (error) {
      console.error('[PROJECTS] Failed to select all matching projects:', error)
      showToast({ message: 'Could not load every matching project. Nothing was selected beyond this page.', type: 'error' })
    } finally {
      busy.value = false
    }
  }

  async function run(verb, rows, action, opts) {
    busy.value = true
    try {
      const result = await runBulk(rows, action, opts)
      const leftover = new Set([...result.skipped, ...result.failed].map(({ row }) => row.id))
      const remaining = bulk.selectedItems.value.filter((p) => leftover.has(p.id) || !rows.includes(p))
      bulk.setSelectedIds(
        remaining.map((p) => p.id),
        remaining,
      )
      showToast({ message: describeBulkResult(verb, result), type: bulkResultType(result) })
      await Promise.all([reloadProjects(), projectStore.fetchHiddenProjects()])
      return result
    } finally {
      busy.value = false
    }
  }

  function archiveSelected() {
    const rows = bulk.selectedItems.value.filter((p) => !p.hidden)
    return run('archived', rows, (p) => projectStore.updateProject(p.id, { hidden: true }), { skipReason: inChainSkip })
  }

  function unarchiveSelected() {
    const rows = bulk.selectedItems.value.filter((p) => p.hidden)
    return run('unarchived', rows, (p) => projectStore.updateProject(p.id, { hidden: false }))
  }

  function deleteSelected() {
    return run('deleted', bulk.selectedItems.value.slice(), (p) => projectStore.deleteProject(p.id), {
      skipReason: inChainSkip,
    })
  }

  function chainSelected() {
    if (!chainReady.value) return
    chainRows.value = chainEligibleRows.value.slice()
    showChainDialog.value = true
  }

  function onChainStarted() {
    bulk.clear()
  }

  return {
    bulk,
    busy,
    canArchive,
    canUnarchive,
    chainReady,
    chainNote,
    showChainDialog,
    chainRows,
    onSelectedIds,
    selectAllMatching,
    archiveSelected,
    unarchiveSelected,
    deleteSelected,
    chainSelected,
    onChainStarted,
  }
}
