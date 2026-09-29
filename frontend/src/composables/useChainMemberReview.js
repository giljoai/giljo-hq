import { ref } from 'vue'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useChainMemberReview({ chainCtx }) {
  const sequenceRunStore = useSequenceRunStore()
  const { showToast } = useToast()

  const showChainReview = ref(false)
  const chainReviewTab = ref(null)

  function handleTabReview(tab) {
    chainReviewTab.value = tab
    showChainReview.value = true
  }

  function handleChainReviewComplete() {
    showChainReview.value = false
    const runId = chainCtx.value?.runId
    const reviewedPid = chainReviewTab.value?.projectId
    chainReviewTab.value = null
    if (!runId || !reviewedPid) return

    sequenceRunStore.markReviewed(runId, reviewedPid)
    sequenceRunStore.markReviewedRemote(runId, reviewedPid).catch((err) => {
      const msg = parseErrorResponse(err).message || 'Could not save the review; it may reappear after refresh.'
      showToast({ message: msg, type: 'error', timeout: 5000 })
    })
  }

  return { showChainReview, chainReviewTab, handleTabReview, handleChainReviewComplete }
}
