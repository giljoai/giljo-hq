import api from '@/services/api'
import { toolIdForSurface } from '@/config/setupTools'

export function useHostedAppPreselect({ currentStep, savedTools, selected, visibleTools, enabled = () => true }) {
  async function preselect() {
    if (!enabled() || currentStep() !== 0 || savedTools().length > 0) return
    try {
      const { data } = await api.connect.credentialStatus()
      if (!enabled() || savedTools().length > 0 || selected.value.length > 0) return
      const visible = new Set(visibleTools().map((t) => t.id))
      const ids = (data?.connected_surfaces || []).map(toolIdForSurface).filter((id) => id && visible.has(id))
      if (ids.length > 0) selected.value = ids
    } catch (e) {
      console.warn('[SetupWizardOverlay] Could not read stored approvals:', e)
    }
  }
  return preselect()
}
