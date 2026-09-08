import { watch } from 'vue'
import api from '@/services/api'
import { toolIdForHarness } from '@/config/setupTools'

/**
 * FE-9569 detector 2, second cause (confirmed live against a real backend
 * during manual verification for this project, not just inferred):
 * WelcomeView.vue seeds SetupWizardOverlay's `currentStep` from the user's
 * PERSISTED `setup_step_completed` on every mount
 * (`setupStep.value = Math.min(setupStepCompleted.value, 3)`). A user who
 * reached Install in an earlier session -- or simply reloads the page while
 * on Install -- gets the overlay mounted DIRECTLY at `currentStep >= 2`:
 * SetupStep2Connect (index 1) never mounts in THIS session, so
 * `step2Data.connectedTools` stays at its fresh empty default forever.
 * SetupStep3Commands' per-tool install-status map then has no key for the
 * tool that already connected, so no amount of re-running `giljo_setup` can
 * ever tick it -- the map it would flip on was never seeded. This is the
 * exact pattern behind the operator's "was already installed and re-ran it;
 * nothing ticked" report.
 *
 * Fix: watch `currentStep` (not a plain `onMounted` check -- see below) and
 * seed `connectedTools` from the SAME durable credential-status truth
 * detector 1 already uses (same idiom as
 * SetupStep2Connect.loadCredentialStatus / ToolsConnectDirectory).
 *
 * WHY WATCH, NOT onMounted: `currentStep` starts at whatever the parent's
 * ref defaults to (0) and is often bumped to its real resumed value
 * ASYNCHRONOUSLY afterward (WelcomeView's onMounted awaits
 * configService.fetchConfig() before setting `setupStep.value`) -- a plain
 * onMounted check here would run BEFORE that update lands and would always
 * see currentStep=0. Watching re-evaluates the moment currentStep actually
 * reaches Install, whenever that happens to be.
 *
 * @param {object} opts
 * @param {() => number} opts.currentStep - getter for the wizard's current step index.
 * @param {() => string[]} opts.selectedTools - getter for the tool ids this wizard run covers.
 * @param {import('vue').Ref<{connectedTools?: string[]}>} opts.step2Data - the host's step2Data ref (mutated in place on seed).
 */
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
