import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'

export const useTemplateProposalsStore = defineStore('templateProposals', () => {
  const proposals = ref([])
  const count = ref(0)
  const loaded = ref(false)
  let inFlight = null

  const byTemplateId = computed(() => {
    const map = {}
    for (const p of proposals.value) {
      if (p?.target_kind === 'agent_template' && p.template_id) map[p.template_id] = p
    }
    return map
  })

  function additionsProposalFor(rung, productId = null) {
    return (
      proposals.value.find(
        (p) =>
          p?.target_kind === 'orchestrator_additions' &&
          p.rung === rung &&
          (rung === 'tenant' || p.product_id === productId),
      ) || null
    )
  }

  async function fetchCount() {
    const res = await api.templateProposals.count()
    count.value = Number(res?.data?.count) || 0
    return count.value
  }

  async function fetchAll() {
    const res = await api.templateProposals.list()
    const list = res?.data?.proposals
    if (!Array.isArray(list)) throw new Error('Template proposals reply has no proposals list')
    proposals.value = list
    const serverCount = Number(res?.data?.count)
    count.value = Number.isFinite(serverCount) ? serverCount : list.length
    loaded.value = true
    return list
  }

  function ensureLoaded() {
    if (loaded.value) return Promise.resolve(proposals.value)
    if (!inFlight) {
      inFlight = fetchAll()
        .catch(() => proposals.value)
        .finally(() => {
          inFlight = null
        })
    }
    return inFlight
  }

  async function settle(id) {
    const before = proposals.value.length
    proposals.value = proposals.value.filter((p) => p.id !== id)
    if (proposals.value.length < before) count.value = Math.max(0, count.value - 1)
    try {
      await fetchAll()
    } catch {
      /* the local drop above already reflects the decision */
    }
  }

  async function apply(id) {
    const res = await api.templateProposals.apply(id)
    await settle(id)
    return res?.data
  }

  async function reject(id) {
    const res = await api.templateProposals.reject(id)
    await settle(id)
    return res?.data
  }

  return {
    proposals,
    count,
    loaded,
    byTemplateId,
    additionsProposalFor,
    fetchCount,
    fetchAll,
    ensureLoaded,
    apply,
    reject,
  }
})
