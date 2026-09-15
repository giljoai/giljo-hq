import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import {
  MAX_SEQUENCE_PROJECTS,
  DEFAULT_EXECUTION_MODE,
  computeChains,
  isChainLocked,
  orderByRoadmap,
  normalizeChainOrder,
} from '@/utils/sequenceOrder'

export function useSequenceRunner() {
  const router = useRouter()
  const { showToast } = useToast()

  const creating = ref(false)

  const selection = ref(new Map())
  const selectedIds = computed(() => Array.from(selection.value.keys()))
  const selectedCount = computed(() => selection.value.size)
  const electionActive = computed(() => selection.value.size >= 2)

  function toggle(item) {
    const id = item?.project_id || item?.id
    if (!id) return
    const next = new Map(selection.value)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.set(id, {
        id,
        name: item.name || item.title || '(untitled)',
        taxonomy_alias: item.taxonomy_alias || '',
      })
    }
    selection.value = next
  }

  function clear() {
    selection.value = new Map()
  }

  async function resolveRunOrder(selected) {
    const rows = (selected || []).map((p) => ({
      project_id: p.id || p.project_id,
      name: p.name || p.title || '(untitled)',
      taxonomy_alias: p.taxonomy_alias || '',
    }))
    const orderMap = new Map()
    try {
      const { data } = await api.roadmap.get()
      const items = Array.isArray(data?.items) ? data.items : []
      for (const it of items) {
        if (it.item_type === 'project' && it.project_id != null) {
          orderMap.set(it.project_id, it.sort_order ?? 0)
        }
      }
    } catch (err) {
      console.warn('[useSequenceRunner] roadmap unavailable; using selection order', err)
    }
    const chains = computeChains(rows)
    const ordered = normalizeChainOrder(orderByRoadmap(rows, orderMap), chains)
    return ordered.map((r) => ({ ...r, locked: isChainLocked(r, chains) }))
  }

  async function startSequence({ projectIds, resolvedOrder, executionMode }) {
    if (creating.value) return null
    if (!resolvedOrder?.length || resolvedOrder.length > MAX_SEQUENCE_PROJECTS) {
      showToast({
        message: `Select 1–${MAX_SEQUENCE_PROJECTS} projects to run sequentially.`,
        type: 'warning',
      })
      return null
    }
    creating.value = true
    try {
      const project_statuses = {}
      for (const pid of resolvedOrder) project_statuses[pid] = 'pending'
      const { data } = await api.sequenceRuns.create({
        project_ids: projectIds || resolvedOrder,
        resolved_order: resolvedOrder,
        execution_mode: executionMode || DEFAULT_EXECUTION_MODE,
        review_policy: 'per_card',
        status: 'pending',
        current_index: 0,
        project_statuses,
      })
      const headPid = data.resolved_order?.[0] || resolvedOrder?.[0]
      router.push({ name: 'ProjectLaunch', params: { projectId: headPid }, query: { run: data.id } })
      return data
    } catch (err) {
      const detail = err?.response?.data?.detail
      const message =
        typeof detail === 'string'
          ? detail
          : 'Could not start the sequence. Check your selection and try again.'
      showToast({ message, type: 'error' })
      return null
    } finally {
      creating.value = false
    }
  }

  return {
    creating,
    selection,
    selectedIds,
    selectedCount,
    electionActive,
    toggle,
    clear,
    resolveRunOrder,
    startSequence,
  }
}
