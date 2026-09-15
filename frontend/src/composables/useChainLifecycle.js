import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

export function useChainLifecycle() {
  const { showToast } = useToast()
  const { copy } = useClipboard()
  const sequenceRunStore = useSequenceRunStore()

  async function stageChain(run) {
    try {
      const updated = await sequenceRunStore.lockRun(run.id)
      const { data } = await api.prompts.chainStaging(run.id)
      const prompt = data?.prompt
      if (prompt) {
        const copied = await copy(prompt)
        if (copied) {
          showToast({
            message: 'Chain staged. Staging prompt copied — paste it into your orchestrator terminal.',
            type: 'success',
            timeout: 6000,
          })
        } else {
          showToast({
            message: 'Chain staged. Browser blocked clipboard — copy the staging prompt manually.',
            type: 'warning',
            timeout: 6000,
          })
        }
      } else {
        showToast({
          message: 'Chain staged (no staging prompt available yet).',
          type: 'success',
          timeout: 4000,
        })
      }
      return updated
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'Could not stage the chain.'
      showToast({ message: msg, type: 'error', timeout: 5000 })
      return null
    }
  }

  async function unstageChain(run) {
    try {
      const updated = await sequenceRunStore.unlockRun(run.id)
      showToast({
        message: 'Chain unstaged — tickboxes unlocked. You can edit membership and re-stage.',
        type: 'success',
        timeout: 5000,
      })
      return updated
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'Could not unstage the chain.'
      showToast({ message: msg, type: 'error', timeout: 5000 })
      return null
    }
  }

  return { stageChain, unstageChain }
}
