import { ref, computed } from 'vue'
import { api } from '@/services/api'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useChainLifecycle } from '@/composables/useChainLifecycle'
import { useChainImplementation } from '@/composables/useChainImplementation'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'
import { buildChainScreenControls } from '@/components/projects/chainScreenVisibility.js'
import { parseErrorResponse } from '@/utils/errorMessages'

function errorText(err, fallback) {
  return parseErrorResponse(err).message || fallback
}

export function useChainGroupControls({ chainCtx }) {
  const sequenceRunStore = useSequenceRunStore()
  const { stageChain, unstageChain } = useChainLifecycle()
  const { launchChainHead } = useChainImplementation()
  const { copy } = useClipboard()
  const { showToast } = useToast()

  const chainStaging = ref(false)
  const launching = ref(false)
  const chainStopping = ref(false)
  const showChainStopConfirm = ref(false)
  const deactivating = ref(false)
  const showDeactivateConfirm = ref(false)

  const chainScreenControls = computed(() =>
    buildChainScreenControls(chainCtx.value, sequenceRunStore.isRunning(chainCtx.value?.runId)),
  )

  const chainStageText = computed(() => (chainCtx.value?.locked ? 'Unstage Chain' : 'Stage Chain'))
  const chainStageDisabled = computed(() => chainStaging.value || !chainCtx.value?.run?.execution_mode)
  const chainStageTitle = computed(() => {
    if (!chainCtx.value) return ''
    if (chainCtx.value.locked) return 'Unlock the chain to edit descriptions, order, and mode'
    if (!chainCtx.value.run?.execution_mode) return 'Select an execution mode first'
    return 'Lock the chain and copy the staging prompt'
  })

  const chainImplementReady = computed(() => {
    const ctx = chainCtx.value
    if (!ctx || ctx.locked !== true || launching.value) return false
    const run = ctx.run
    if (!(run?.chain_mission ?? '').trim()) return false
    return run?.status === 'pending' || run?.status === 'staged'
  })

  const showCopyMasterPrompt = computed(
    () =>
      chainCtx.value?.locked === true &&
      chainCtx.value?.run?.execution_mode === 'multi_terminal' &&
      !chainScreenControls.value.showStopChain,
  )

  async function patchRunMode(mode) {
    if (!chainCtx.value || chainCtx.value.locked) return
    try {
      await sequenceRunStore.patchRun(chainCtx.value.runId, { execution_mode: mode })
    } catch (err) {
      showToast({ message: errorText(err, 'Could not change the chain execution mode.'), type: 'error', timeout: 5000 })
    }
  }

  async function handleChainStage() {
    if (!chainCtx.value) return
    chainStaging.value = true
    try {
      if (chainCtx.value.locked) {
        await unstageChain(chainCtx.value.run)
      } else {
        await stageChain(chainCtx.value.run)
      }
    } finally {
      chainStaging.value = false
    }
  }

  async function handleChainImplement() {
    const ctx = chainCtx.value
    if (!ctx) return false
    const run = ctx.run
    const headPid = run?.resolved_order?.[0] || run?.project_ids?.[0] || ctx.tabs?.[0]?.projectId || null
    launching.value = true
    try {
      return await launchChainHead(headPid)
    } finally {
      launching.value = false
    }
  }

  async function copyPrompt(fetchPrompt, successMessage, failureMessage) {
    try {
      const { data } = await fetchPrompt()
      const prompt = data?.prompt
      if (!prompt) throw new Error('No prompt text returned')
      if (await copy(prompt)) {
        showToast({ message: successMessage, type: 'success', timeout: 5000 })
      } else {
        showToast({ message: 'Browser blocked clipboard access. Try again.', type: 'error', timeout: 6000 })
      }
    } catch (err) {
      showToast({ message: errorText(err, failureMessage), type: 'error', timeout: 6000 })
    }
  }

  function copyMasterPrompt() {
    const runId = chainCtx.value?.runId
    if (!runId) return Promise.resolve()
    return copyPrompt(
      () => api.prompts.chainImplementation(runId),
      'Master prompt copied. Paste it into one terminal to drive the chain.',
      'Could not build the master prompt.',
    )
  }

  function copyMemberFallbackPrompt(projectId) {
    if (!projectId) return Promise.resolve()
    return copyPrompt(
      () => api.prompts.chainMemberFallback(projectId),
      'Fallback prompt copied. It runs this project only.',
      'Could not build the fallback prompt.',
    )
  }

  function openChainStopConfirm() {
    showChainStopConfirm.value = true
  }

  function cancelChainStop() {
    showChainStopConfirm.value = false
  }

  async function handleChainStop() {
    const runId = chainCtx.value?.runId
    if (!runId || chainStopping.value) return
    chainStopping.value = true
    try {
      await sequenceRunStore.stopChain(runId)
      showChainStopConfirm.value = false
      showToast({ message: 'Chain stopped.', type: 'success' })
    } catch (err) {
      showToast({ message: errorText(err, 'Could not stop the chain.'), type: 'error', timeout: 5000 })
    } finally {
      chainStopping.value = false
    }
  }

  function openDeactivateConfirm() {
    showDeactivateConfirm.value = true
  }

  function cancelDeactivate() {
    showDeactivateConfirm.value = false
  }

  async function handleChainDeactivate() {
    const runId = chainCtx.value?.runId
    if (!runId || deactivating.value) return
    deactivating.value = true
    try {
      await sequenceRunStore.deactivateChain(runId)
      showDeactivateConfirm.value = false
      showToast({ message: 'Chain deactivated. Its projects are back to their original state.', type: 'success' })
    } catch (err) {
      showToast({ message: errorText(err, 'Could not deactivate the chain.'), type: 'error', timeout: 5000 })
    } finally {
      deactivating.value = false
    }
  }

  return {
    chainScreenControls,
    chainStaging,
    launching,
    chainStageText,
    chainStageDisabled,
    chainStageTitle,
    chainImplementReady,
    showCopyMasterPrompt,
    patchRunMode,
    handleChainStage,
    handleChainImplement,
    copyMasterPrompt,
    copyMemberFallbackPrompt,
    chainStopping,
    showChainStopConfirm,
    openChainStopConfirm,
    cancelChainStop,
    handleChainStop,
    deactivating,
    showDeactivateConfirm,
    openDeactivateConfirm,
    cancelDeactivate,
    handleChainDeactivate,
  }
}
