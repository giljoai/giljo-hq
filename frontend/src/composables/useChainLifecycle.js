import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { parseErrorResponse } from '@/utils/errorMessages'

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
            message: 'Chain staged. Staging prompt copied; paste it into your orchestrator terminal.',
            type: 'success',
          })
        } else {
          showToast({
            message: 'Chain staged. Your browser blocked the clipboard, so copy the staging prompt manually.',
            type: 'warning',
          })
        }
      } else {
        showToast({
          message: 'Chain staged (no staging prompt available yet).',
          type: 'success',
        })
      }
      return updated
    } catch (err) {
      const msg = parseErrorResponse(err).message || 'Could not stage the chain.'
      showToast({ message: msg, type: 'error' })
      return null
    }
  }

  async function unstageChain(run) {
    try {
      const updated = await sequenceRunStore.unlockRun(run.id)
      showToast({
        message: 'Chain unstaged. You can edit its projects, order and mode, then stage it again.',
        type: 'success',
      })
      return updated
    } catch (err) {
      const msg = parseErrorResponse(err).message || 'Could not unstage the chain.'
      showToast({ message: msg, type: 'error' })
      return null
    }
  }

  return { stageChain, unstageChain }
}
