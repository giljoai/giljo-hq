import { computed, watch } from 'vue'
import { useProjectStateStore } from '@/stores/projectStateStore'
import { useExecutionMode } from '@/composables/useExecutionMode'
import { useProjectStaging } from '@/composables/useProjectStaging'
import { useSettingsStore } from '@/stores/settings'
import { preselectedExecutionMode } from '@/utils/executionModeDefault'

export function isProjectLaunched(project, state) {
  return Boolean(project?.implementation_launched_at || state?.implementationLaunched || state?.isLaunched)
}

export function useProjectStageControls({ project, seedState = false }) {
  const projectStateStore = useProjectStateStore()

  const getProject = typeof project === 'function' ? project : () => project?.value
  const projectId = computed(() => getProject()?.project_id || getProject()?.id || null)
  const projectState = computed(() => projectStateStore.getProjectState(projectId.value))

  if (seedState) {
    watch(
      getProject,
      (proj) => {
        if (proj) projectStateStore.setProject(proj)
      },
      { immediate: true },
    )
  }

  const missionText = computed(() => projectState.value?.mission || '')
  const isProjectStaged = computed(() => Boolean(projectState.value?.isStaged))
  const isProjectStaging = computed(() => Boolean(projectState.value?.isStaging))

  const modeIsFact = computed(() =>
    Boolean(
      isProjectStaged.value ||
        isProjectStaging.value ||
        projectState.value?.stagingComplete ||
        isProjectLaunched(getProject(), projectState.value),
    ),
  )

  const {
    executionPlatform,
    executionMode,
    executionModeSelected,
    isExecutionModeLocked,
    agenticTool,
    handleExecutionModeChange: changeMode,
  } = useExecutionMode({
    projectId,
    missionText,
    isProjectStaged,
    isProjectStaging,
    initialMode: getProject()?.execution_mode || null,
    modeIsFact,
  })

  watch(
    [() => getProject()?.execution_mode, modeIsFact],
    ([newMode, fact]) => {
      executionMode.value = newMode || null
      if (fact && newMode) {
        executionPlatform.value = newMode
      } else if (!fact && newMode !== executionPlatform.value) {
        executionPlatform.value = null
      }
    },
    { immediate: true },
  )

  const settingsStore = useSettingsStore()
  settingsStore.ensureExecutionModeDefault()
  watch(
    [() => settingsStore.executionModeDefault, modeIsFact, executionPlatform],
    ([accountDefault, fact, picked]) => {
      const preset = preselectedExecutionMode(accountDefault)
      if (fact || picked || !preset) return
      executionPlatform.value = preset
      executionMode.value = preset
    },
    { immediate: true },
  )

  const handleExecutionModeChange = changeMode

  const readyToLaunch = computed(() =>
    Boolean(projectState.value?.stagingComplete && !projectState.value?.isStaging),
  )

  const canRestage = computed(() =>
    Boolean(
      projectState.value?.stagingComplete &&
        !projectState.value?.implementationLaunched &&
        !projectState.value?.isStaging,
    ),
  )

  const hasActiveOrchestrator = computed(() => Boolean(projectState.value?.stagingComplete))
  const implementationLaunched = computed(() => Boolean(projectState.value?.implementationLaunched))
  const launched = computed(() => isProjectLaunched(getProject(), projectState.value))

  const {
    loadingStageProject,
    handleStageOrRestage: stageOrRestage,
    handleLaunchJobs: launchJobs,
    onLaunchSuccess,
  } = useProjectStaging({
    projectId,
    executionMode,
    isProjectStaged,
    readyToLaunch,
    canRestage,
  })

  const freshStage = computed(() => !isProjectStaged.value && !isProjectStaging.value && !canRestage.value)

  const stageNeedsMode = computed(() => freshStage.value && !executionModeSelected.value)

  async function handleStageOrRestage() {
    const wasStagedOrRestage = isProjectStaged.value || canRestage.value
    await stageOrRestage()
    if (wasStagedOrRestage) executionPlatform.value = null
  }

  function handleLaunchJobs() {
    return launchJobs(getProject())
  }

  const stageButtonText = computed(() => {
    if (isProjectStaging.value) return 'Staging...'
    if (isProjectStaged.value) return 'Unstage'
    if (canRestage.value) return 'Re-Stage'
    return 'Stage'
  })

  const stageButtonDisabled = computed(() => {
    if (isProjectStaging.value) return true
    if (isProjectStaged.value) return false
    if (hasActiveOrchestrator.value && implementationLaunched.value) return true
    if (canRestage.value) return false
    return hasActiveOrchestrator.value
  })

  const stageButtonTitle = computed(() => {
    if (isProjectStaging.value) return 'Staging is in progress. The agent is working.'
    if (isProjectStaged.value) return 'Revert to ready state (before agent makes contact)'
    if (hasActiveOrchestrator.value && implementationLaunched.value) {
      return 'Cannot recover: implementation has already launched'
    }
    if (canRestage.value) return 'Reset staging so you can change execution mode and stage again'
    if (!executionModeSelected.value) return 'Pick a mode, then stage'
    if (hasActiveOrchestrator.value) return 'An orchestrator is already active for this project'
    return 'Generate orchestrator prompt'
  })

  const canImplement = computed(() => executionModeSelected.value && readyToLaunch.value)

  return {
    projectId,
    missionText,
    isProjectStaged,
    isProjectStaging,
    readyToLaunch,
    canRestage,
    canImplement,
    implementationLaunched,
    launched,
    executionPlatform,
    executionMode,
    executionModeSelected,
    isExecutionModeLocked,
    modeIsFact,
    stageNeedsMode,
    agenticTool,
    handleExecutionModeChange,
    loadingStageProject,
    handleStageOrRestage,
    handleLaunchJobs,
    onLaunchSuccess,
    stageButtonText,
    stageButtonDisabled,
    stageButtonTitle,
  }
}
