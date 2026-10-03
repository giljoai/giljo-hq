import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import { parseErrorResponse } from '@/utils/errorMessages'

export const useApprovalsStore = defineStore('approvals', () => {
  const approvalsById = ref(new Map())
  const loading = ref(false)
  const error = ref(null)

  const pendingApprovals = computed(() => Array.from(approvalsById.value.values()))

  const findByJobId = (jobId) => {
    if (!jobId) return null
    for (const row of approvalsById.value.values()) {
      if (row.job_id === jobId) return row
    }
    return null
  }

  async function fetchPending() {
    loading.value = true
    error.value = null
    try {
      const res = await api.approvals.listPending()
      const items = res?.data?.items
      if (!Array.isArray(items)) throw new Error('Pending approvals reply has no items list')
      const next = new Map()
      for (const item of items) {
        if (item?.id) next.set(item.id, item)
      }
      approvalsById.value = next
      return items
    } catch (err) {
      error.value = parseErrorResponse(err).message
      throw err
    } finally {
      loading.value = false
    }
  }

  function upsertApproval(row) {
    if (!row?.id) return
    const next = new Map(approvalsById.value)
    next.set(row.id, row)
    approvalsById.value = next
  }

  function removeApproval(approvalId) {
    if (!approvalId || !approvalsById.value.has(approvalId)) return
    const next = new Map(approvalsById.value)
    next.delete(approvalId)
    approvalsById.value = next
  }

  async function handleStatusEvent(payload) {
    if (!payload) return
    if (payload.decided_option_id && payload.user_approval_id) {
      removeApproval(payload.user_approval_id)
      return
    }
    if (payload.status === 'awaiting_user' && payload.user_approval_id) {
      try {
        await fetchPending()
      } catch {
        // Swallow: error already surfaced via store.error
      }
    }
  }

  async function decide(approvalId, optionId) {
    if (!approvalId || !optionId) {
      throw new Error('approvalId and optionId are required')
    }
    const res = await api.approvals.decide(approvalId, optionId)
    return res?.data
  }

  function $reset() {
    approvalsById.value = new Map()
    loading.value = false
    error.value = null
  }

  return {
    approvalsById,
    loading,
    error,
    pendingApprovals,
    findByJobId,
    fetchPending,
    upsertApproval,
    removeApproval,
    handleStatusEvent,
    decide,
    $reset,
  }
})
