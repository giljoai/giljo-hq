
import { ref, onMounted } from 'vue'
import setupService from '@/services/setupService'

export function useIntegrationStatus({ immediate = true } = {}) {
  const gitEnabled = ref(false)
  const loading = ref(immediate)
  const resolved = ref(false)

  async function loadStatus() {
    loading.value = true
    try {
      const gitSettings = await setupService.getGitSettings()
      gitEnabled.value = gitSettings.enabled || false
      resolved.value = true
    } catch (error) {
      console.error('[useIntegrationStatus] Failed to load:', error)
    } finally {
      loading.value = false
    }
  }

  if (immediate) {
    onMounted(loadStatus)
  }

  return { gitEnabled, loading, resolved, refresh: loadStatus }
}
