/**
 * useChainLifecycle — FE-6165f / FE-6170 / FE-6171b
 *
 * Lifecycle control actions for a running sequential chain:
 *   - stageChain        lock the run (PATCH locked=true) + copy staging prompt
 *   - unstageChain      unlock the run (PATCH locked=false) — KEEP chain intact (FE-6171b redef)
 *
 * FE-9503a: terminateChain/handoverConductor/releaseChain/resumeChain were
 * removed as zero-caller dead code (verified by call path, not grep hit --
 * dossier in the FE-9503a project record). Only stageChain/unstageChain have
 * a live production caller (useChainTabControls.js).
 *
 * FE-6170 → FE-6171b REDEFINITION:
 *   unstageChain was "cancel+dissolve" in FE-6170. In FE-6171b it is UNLOCK ONLY —
 *   the chain stays intact.
 *
 * All flows operate over existing API endpoints — NO new writers.
 * Edition scope: CE.
 */
import { api } from '@/services/api'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'

export function useChainLifecycle() {
  const { showToast } = useToast()
  const { copy } = useClipboard()
  const sequenceRunStore = useSequenceRunStore()

  /**
   * stageChain — FE-6171b Stage action (Editing → Staged tier).
   *
   * 1. PATCH run locked=true via the store (single write seam).
   * 2. Fetch the chain staging prompt and copy it to the clipboard.
   *
   * Replicates the solo Stage button in ProjectTabs.vue / useProjectStaging.
   * The dynamic Stage⇄Unstage button in ChainCockpitControls calls this.
   *
   * @param {Object} run - the sequence run object
   * @returns {Promise<Object|null>} updated run on success, null on error
   */
  async function stageChain(run) {
    try {
      const updated = await sequenceRunStore.lockRun(run.id)
      // Fetch and copy the chain staging prompt (mirrors useChainStaging.copyStagingPrompt).
      const { data } = await api.prompts.chainStaging(run.id)
      const prompt = data?.prompt
      if (prompt) {
        const copied = await copy(prompt)
        if (copied) {
          showToast({
            message: 'Chain staged. Staging prompt copied — paste it into your orchestrator terminal.',
            type: 'success',
            timeout: 6000,
          })
        } else {
          showToast({
            message: 'Chain staged. Browser blocked clipboard — copy the staging prompt manually.',
            type: 'warning',
            timeout: 6000,
          })
        }
      } else {
        showToast({
          message: 'Chain staged (no staging prompt available yet).',
          type: 'success',
          timeout: 4000,
        })
      }
      return updated
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'Could not stage the chain.'
      showToast({ message: msg, type: 'error', timeout: 5000 })
      return null
    }
  }

  /**
   * unstageChain — FE-6171b Unstage action (Staged → Editing tier).
   *
   * UNLOCK ONLY — PATCHes locked=false. The chain stays intact.
   * This is a REDEFINITION from FE-6170 (where unstage dissolved the run).
   *
   * The BE refuses with HTTP 422 at the ultralock tier (run is running/stalled,
   * or any member project has staging_status == 'staging_complete'). This function
   * surfaces that 422 gracefully — the caller (ChainCockpitControls) hides the
   * button at ultralock, so this is defense-in-depth.
   *
   * @param {Object} run - the sequence run object
   * @returns {Promise<Object|null>} updated run on success, null on error
   */
  async function unstageChain(run) {
    try {
      const updated = await sequenceRunStore.unlockRun(run.id)
      showToast({
        message: 'Chain unstaged — tickboxes unlocked. You can edit membership and re-stage.',
        type: 'success',
        timeout: 5000,
      })
      return updated
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        'Could not unstage the chain.'
      showToast({ message: msg, type: 'error', timeout: 5000 })
      return null
    }
  }

  return { stageChain, unstageChain }
}
