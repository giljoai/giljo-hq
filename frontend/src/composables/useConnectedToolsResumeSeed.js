import { watch } from 'vue'
import api from '@/services/api'
import { toolIdForHarness } from '@/config/setupTools'

export function useConnectedToolsResumeSeed({ currentStep, selectedTools, step2Data }) {
  let seeded = false

  async function seed() {
    if (seeded) return
    if (currentStep() < 2) return
    if (step2Data.value?.connectedTools?.length) return
    seeded = true
    try {
      const { data } = await api.connect.credentialStatus()
      const connectedHarnesses = data?.connected_harnesses || {}
      const ids = new Set()
      for (const harness of Object.keys(connectedHarnesses)) {
        const id = toolIdForHarness(harness)
        if (id && selectedTools().includes(id)) ids.add(id)
      }
      if (ids.size > 0) {
        step2Data.value = { ...step2Data.value, connectedTools: [...ids] }
      }
    } catch (e) {
      console.warn('[useConnectedToolsResumeSeed] Failed to seed connectedTools on resume:', e)
    }
  }

  watch(currentStep, seed, { immediate: true })
}
