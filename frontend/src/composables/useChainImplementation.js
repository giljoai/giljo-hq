import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useChainImplementation() {
  const { showToast } = useToast()

  async function launchChainHead(headProjectId) {
    if (!headProjectId) return false
    try {
      await api.projects.launchImplementation(headProjectId)
      return true
    } catch (err) {
      const msg = parseErrorResponse(err).message || 'Could not start the first project in this chain.'
      showToast({ message: msg, type: 'error' })
      return false
    }
  }

  return { launchChainHead }
}
