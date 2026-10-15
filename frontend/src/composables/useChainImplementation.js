import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useProjectTabsStore } from '@/stores/projectTabs'
import { parseErrorResponse } from '@/utils/errorMessages'

export function useChainImplementation() {
  const { showToast } = useToast()
  const tabsStore = useProjectTabsStore()

  async function launchChainHead(headProjectId) {
    if (!headProjectId) return false
    try {
      await api.projects.launchImplementation(headProjectId)
      tabsStore.noteUserImplement({ id: headProjectId })
      return true
    } catch (err) {
      const msg = parseErrorResponse(err).message || 'Could not start the first project in this chain.'
      showToast({ message: msg, type: 'error' })
      return false
    }
  }

  return { launchChainHead }
}
