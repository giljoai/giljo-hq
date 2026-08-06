/**
 * Integration Status Composable (Handover 0427)
 *
 * Fetches and manages Git and Serena MCP integration status.
 * Used to display integration status icons in the UI.
 */

import { ref, onMounted } from 'vue'
import setupService from '@/services/setupService'

/**
 * @param {Object} [options]
 * @param {boolean} [options.immediate=true] - fetch git/serena status on mount.
 *   Pass `false` to defer the fetch (FE-6059): callers that only show
 *   integration status conditionally (e.g. Home's onboarding reminder) can
 *   invoke the returned `refresh()` when the consuming UI actually renders,
 *   keeping /api/git/settings + /api/serena/status off the cold first paint.
 */
export function useIntegrationStatus({ immediate = true } = {}) {
  const gitEnabled = ref(false)
  const serenaEnabled = ref(false)
  const loading = ref(immediate)
  // FE-9233: `false` here means BOTH "known to be disabled" and "not read yet",
  // and callers had no way to tell them apart -- so UI rendered from defaults.
  // `resolved` is true only after a SUCCESSFUL read. Consumers whose UI must
  // not render from unproven data gate on this: the onboarding nudge hides
  // itself (FE-9233), and the integration status icons render a neutral
  // pending treatment instead of asserting "disabled" (TSK-9234).
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
      // Keep defaults (false) on error -- and deliberately leave `resolved`
      // false so a transient failure (the 429 storm FE-9233 item 1 covers)
      // reads as "unknown", not as "integrations are off".
    } finally {
      loading.value = false
    }
  }

  if (immediate) {
    onMounted(loadStatus)
  }

  return { gitEnabled, serenaEnabled, loading, resolved, refresh: loadStatus }
}
