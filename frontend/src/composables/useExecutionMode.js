/**
 * useExecutionMode.js — FE-6006 unit 3a
 *
 * Extracted from ProjectTabs.vue: manages execution-mode selection,
 * lock state, button computeds, and the platform → API persistence flow.
 * Edition scope: CE
 */
import { ref, computed } from 'vue'
import { useToast } from '@/composables/useToast'
import { useProjectStore } from '@/stores/projects'
import { useNotificationStore } from '@/stores/notifications'
import { notifyFailure } from '@/utils/notifyFailure'

const GENERIC_EXECUTION_MODE_FAILURE = 'Failed to save execution mode. Please try again.'

/**
 * The tolerated PRE-collapse per-CLI execution_mode tokens (BE-9035a). BE-9035c
 * collapsed the picker to 2 canonical values (multi_terminal / subagent); these 5
 * legacy tokens still live in projects staged before the collapse and are folded to
 * subagent on read by isSubagentExecutionMode() below (the single fold-rule site).
 * Kept as an explicit list so the collapse regression test can assert every legacy
 * token — including generic_mcp — still reads as subagent-style.
 */
export const SUBAGENT_EXECUTION_MODES = ['claude_code_cli', 'codex_cli', 'gemini_cli', 'antigravity_cli', 'generic_mcp']

/**
 * @param {Object} options
 * @param {import('vue').Ref<string|null>} options.projectId
 * @param {import('vue').Ref<string>} options.missionText
 * @param {import('vue').Ref<boolean>} options.isProjectStaged
 * @param {import('vue').Ref<boolean>} options.isProjectStaging
 * @param {string|null} [options.initialMode=null]  initial executionMode (from project.execution_mode)
 */
export function useExecutionMode({ projectId, missionText, isProjectStaged, isProjectStaging, initialMode = null }) {
  const { showToast } = useToast()
  const projectStore = useProjectStore()
  const notificationStore = useNotificationStore()

  // Radio selection (null = user hasn't chosen yet this session)
  const executionPlatform = ref(null)

  // Persisted execution mode (synced to backend; used for staging API calls).
  // NULL-state redesign: stays null until the user explicitly picks a mode, so a
  // never-chosen project sends no mode and the backend gate fires (409) instead
  // of silently staging as multi_terminal. The Stage button is gated separately
  // on executionPlatform (the radio), which is also null-until-chosen.
  const executionMode = ref(initialMode ?? null)

  const executionModeSelected = computed(() => executionPlatform.value !== null)

  /**
   * Execution mode is locked once a mode has been SELECTED and the orchestrator
   * has received a mission (or the project has entered staged / staging state).
   *
   * NULL-state redesign: an UNSELECTED (null) execution mode is never locked, so
   * the user can always pick one to satisfy the staging gate — even on a project
   * that already carries a mission before any mode was chosen (e.g. a
   * CTX-bootstrap project renders its mission at creation). The lock only blocks
   * CHANGING an already-chosen mode after staging.
   */
  const isExecutionModeLocked = computed(
    () =>
      Boolean(executionMode.value) &&
      (Boolean(missionText.value) || isProjectStaged.value || isProjectStaging.value),
  )

  // BE-9035c: execution-mode collapse — only 'multi_terminal' and 'subagent'
  // are ever WRITTEN by the UI now. A handful of legacy per-CLI tokens
  // (claude_code_cli, codex_cli, gemini_cli, antigravity_cli, generic_mcp)
  // are still TOLERATED ON READ for projects staged before the collapse; the
  // fold rule below treats any of them as "subagent" too.
  const isSubagentMode = computed(() => isSubagentExecutionMode(executionMode.value))

  /**
   * Active agentic tool badge — shown in LaunchTab after user selects a mode.
   */
  const agenticTool = computed(() => {
    const mode = executionPlatform.value
    if (!mode) return null
    if (mode === 'multi_terminal') return { type: 'icon', icon: 'mdi-monitor-multiple', label: 'Multi Terminal', alt: 'Multi terminal mode active' }
    // Subagent (and any tolerated legacy CLI token): harness is auto-detected
    // server-side, so there is no per-vendor logo to show here — a single
    // MCP-connection icon covers the collapsed mode.
    return { type: 'icon', icon: 'mdi-connection', label: 'Subagent', alt: 'Subagent mode active' }
  })

  const _modeLabels = {
    multi_terminal: 'Multi-Terminal mode enabled',
    subagent: 'Subagent mode enabled',
  }

  /**
   * Handle radio button change: optimistically update, persist to backend,
   * revert on failure.
   */
  async function handleExecutionModeChange(newValue) {
    const previousValue = executionPlatform.value
    executionPlatform.value = newValue

    try {
      // FE-9122: write through the project store's owning action — its
      // _upsertEntity bridge hydrates projectStateStore synchronously from
      // the response, so JobsTab's store-first execution_mode read (FE-6019)
      // is fresh without waiting on a WS round-trip.
      await projectStore.updateProject(projectId.value, { execution_mode: newValue })
      executionMode.value = newValue
      showToast({
        message: _modeLabels[newValue] || 'Execution mode updated',
        type: 'info',
        timeout: 3000,
      })
    } catch (error) {
      executionPlatform.value = previousValue
      console.error('Failed to update execution mode:', error)
      showToast({
        message: GENERIC_EXECUTION_MODE_FAILURE,
        type: 'error',
        timeout: 3000,
      })
      // FE-9466: persist the server's own reason past the toast.
      notifyFailure(notificationStore, {
        operation: 'project.executionMode',
        entityId: projectId.value,
        error,
        fallbackMessage: GENERIC_EXECUTION_MODE_FAILURE,
        title: 'Execution mode not saved',
      })
    }
  }

  return {
    executionPlatform,
    executionMode,
    executionModeSelected,
    isExecutionModeLocked,
    isSubagentMode,
    agenticTool,
    handleExecutionModeChange,
  }
}

/**
 * Pure (Vue-free) fold rule: is this execution_mode value "subagent-style"?
 * BE-9035c collapsed the picker to 2 canonical values (multi_terminal,
 * subagent); the 5 pre-collapse per-CLI tokens (claude_code_cli, codex_cli,
 * gemini_cli, antigravity_cli, generic_mcp) are tolerated on read for
 * projects staged before the collapse. Anything truthy that isn't
 * 'multi_terminal' folds to subagent — this is the ONE place that rule
 * lives, so JobsTab.vue / usePlayButton.js don't hand-roll their own
 * per-CLI arrays (which is how 'generic_mcp' got missed before).
 *
 * @param {string|null|undefined} mode
 * @returns {boolean}
 */
export function isSubagentExecutionMode(mode) {
  return Boolean(mode) && mode !== 'multi_terminal'
}
