import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'

export function useChainImplementation() {
  const { showToast } = useToast()
  const { copy } = useClipboard()

  async function copyImplPrompt(runId, headProjectId) {
    if (!runId) return false
    if (headProjectId) {
      try {
        await api.projects.launchImplementation(headProjectId)
      } catch (gateError) {
        console.warn('[useChainImplementation] head launch-implementation failed (non-blocking):', gateError)
      }
    }
    try {
      const { data } = await api.prompts.chainImplementation(runId)
      const prompt = data?.prompt
      if (!prompt) throw new Error('No implementation prompt returned')
      const ok = await copy(prompt)
      if (!ok) {
        showToast({
          message: 'Browser blocked clipboard access. Copy the implementation prompt manually.',
          type: 'error',
          timeout: 6000,
        })
        return false
      }
      showToast({
        message: 'Chain implementation prompt copied. Paste it into the head project orchestrator terminal to drive the whole chain.',
        type: 'success',
        timeout: 5000,
      })
      return true
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || 'Could not copy the chain implementation prompt.'
      showToast({ message: msg, type: 'error', timeout: 5000 })
      return false
    }
  }

  return { copyImplPrompt }
}
