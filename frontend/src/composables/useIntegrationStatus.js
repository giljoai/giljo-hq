
import { ref, onMounted } from 'vue'
import setupService from '@/services/setupService'

export function useIntegrationStatus({ immediate = true } = {}) {
  const gitEnabled = ref(false)
  const serenaEnabled = ref(false)
  const loading = ref(immediate)
  const resolved = ref(false)

  async function loadStatus() {
    loading.value = true
    try {
      const [gitSettings, serenaStatus] = await Promise.all([
        setupService.getGitSettings(),
        setupService.getSerenaStatus(),
      ])
      gitEnabled.value = gitSettings.enabled || false
      serenaEnabled.value = serenaStatus.enabled || false
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

  return { gitEnabled, serenaEnabled, loading, resolved, refresh: loadStatus }
}
