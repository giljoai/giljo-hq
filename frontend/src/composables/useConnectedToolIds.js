import { onMounted, ref } from 'vue'

import api from '@/services/api'
import { toolIdForHarness, toolIdForSurface } from '@/config/setupTools'

export function useConnectedToolIds() {
  const connected = ref(new Set())

  async function load() {
    try {
      const { data } = await api.connect.credentialStatus()
      const ids = new Set()
      for (const harness of Object.keys(data?.connected_harnesses || {})) {
        const id = toolIdForHarness(harness)
        if (id) ids.add(id)
      }
      for (const surface of data?.connected_surfaces || []) {
        const id = toolIdForSurface(surface)
        if (id) ids.add(id)
      }
      connected.value = ids
    } catch (e) {
      console.warn('[SetupWizardOverlay] Could not read which tools are connected:', e)
    }
  }

  onMounted(load)
  return { connected, reload: load }
}
