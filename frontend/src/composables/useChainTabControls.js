import { ref, computed } from 'vue'
import { useSequenceRunStore } from '@/stores/sequenceRunStore'
import { useChainLifecycle } from '@/composables/useChainLifecycle'
import { useChainImplementation } from '@/composables/useChainImplementation'
import { useToast } from '@/composables/useToast'
import { buildChainScreenControls } from '@/components/projects/chainScreenVisibility.js'

export function useChainTabControls({ chainCtx, projectId, router, route, activeTab, onUserNav = () => {} }) {
  const sequenceRunStore = useSequenceRunStore()
  const { stageChain, unstageChain } = useChainLifecycle()
  const { launchChainHead } = useChainImplementation()
  const { showToast } = useToast()

  const chainStaging = ref(false)
  const showChainReview = ref(false)
  const chainReviewTab = ref(null)
  const chainStopping = ref(false)
  const showChainStopConfirm = ref(false)

  const chainScreenControls = computed(() =>
    buildChainScreenControls(chainCtx.value, sequenceRunStore.isRunning(chainCtx.value?.runId)),
  )

  const chainStageText = computed(() => (chainCtx.value?.locked ? 'Unstage Chain' : 'Stage Chain'))
  const chainStageDisabled = computed(
    () => chainStaging.value || !chainCtx.value?.run?.execution_mode,
  )
  const chainStageColor = computed(() => {
    if (!chainCtx.value) return undefined
    return chainCtx.value.locked ? undefined : 'yellow-darken-2'
  })
  const chainStageTitle = computed(() => {
    if (!chainCtx.value) return ''
    if (chainCtx.value.locked) return 'Unlock the chain to edit descriptions, order, and mode'
    if (!chainCtx.value.run?.execution_mode) return 'Select an execution mode first'
    return 'Lock the chain and copy the staging prompt'
  })
  const chainImplementReady = computed(() => {
    const ctx = chainCtx.value
    if (!ctx) return false
    const run = ctx.run
    if (ctx.locked !== true) return false
    if (!(run?.chain_mission ?? '').trim()) return false
    return run?.status === 'pending' || run?.status === 'staged'
  })

  async function patchRunMode(mode) {
    if (!chainCtx.value || chainCtx.value.locked) return
    try {
      await sequenceRunStore.patchRun(chainCtx.value.runId, { execution_mode: mode })
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || 'Could not change the chain execution mode.'
      showToast({ message: msg, type: 'error', timeout: 5000 })
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
    if (!chainCtx.value) return
    onUserNav()
    const run = chainCtx.value.run
    const headPid =
      run?.resolved_order?.[0] || run?.project_ids?.[0] || chainCtx.value.tabs?.[0]?.projectId || null
    const ok = await launchChainHead(headPid)
    if (!ok) return

    if (headPid && headPid !== projectId.value) {
      router.push({
        name: 'ProjectLaunch',
        params: { projectId: headPid },
        query: { ...route.query, via: 'jobs' },
      })
    }

    if (activeTab) {
      activeTab.value = 'jobs'
      if (route.query.via !== 'jobs') {
        router.replace({ query: { ...route.query, via: 'jobs' } })
      }
    }
  }

  function handleTabSelect(pid) {
    if (!pid || pid === projectId.value) return
    onUserNav()
    const query = { ...route.query }
    if (sequenceRunStore.isRunning(chainCtx.value?.runId)) query.tab = 'jobs'
    router.push({ name: 'ProjectLaunch', params: { projectId: pid }, query })
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
      router.push({ name: 'Projects' })
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || 'Could not stop the chain.'
      showToast({ message: msg, type: 'error', timeout: 5000 })
    } finally {
      chainStopping.value = false
    }
  }

  function handleTabReview(tab) {
    chainReviewTab.value = tab
    showChainReview.value = true
  }

  function handleChainReviewComplete() {
    showChainReview.value = false
    const runId = chainCtx.value?.runId
    const reviewedPid = chainReviewTab.value?.projectId
    chainReviewTab.value = null

    if (runId && reviewedPid) {
      sequenceRunStore.markReviewed(runId, reviewedPid)
      sequenceRunStore.markReviewedRemote(runId, reviewedPid).catch((err) => {
        const msg =
          err?.response?.data?.detail || err?.message || 'Could not save the review; it may reappear after refresh.'
        showToast({ message: msg, type: 'error', timeout: 5000 })
      })
    }

    const tabs = chainCtx.value?.tabs || []
    const allDone = tabs.length > 0 && tabs.every(
      (t) => t.isCompleted && sequenceRunStore.isReviewed(runId, t.projectId),
    )
    if (allDone) {
      router.push('/projects')
      return
    }
    const nextUnreviewed = tabs.find(
      (t) => t.isCompleted && !sequenceRunStore.isReviewed(runId, t.projectId),
    )
    if (nextUnreviewed && nextUnreviewed.projectId !== reviewedPid) {
      router.push({ name: 'ProjectLaunch', params: { projectId: nextUnreviewed.projectId }, query: { ...route.query } })
    }
  }

  return {
    chainScreenControls,
    chainStaging,
    chainStopping,
    showChainStopConfirm,
    showChainReview,
    chainReviewTab,
    chainStageText,
    chainStageDisabled,
    chainStageColor,
    chainStageTitle,
    chainImplementReady,
    patchRunMode,
    handleChainStage,
    handleChainImplement,
    openChainStopConfirm,
    cancelChainStop,
    handleChainStop,
    handleTabSelect,
    handleTabReview,
    handleChainReviewComplete,
  }
}
