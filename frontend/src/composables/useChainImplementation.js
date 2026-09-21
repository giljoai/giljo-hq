import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'

export function useChainImplementation() {
  const { showToast } = useToast()

  async function launchChainHead(headProjectId) {
    if (!headProjectId) return false
    try {
      await api.projects.launchImplementation(headProjectId)
      return true
    } catch (err) {
      const msg =
        err?.response?.data?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        'Could not start the first project in this chain.'
      showToast({ message: msg, type: 'error', timeout: 6000 })
      return false
    }
  }

  return { launchChainHead }
}
