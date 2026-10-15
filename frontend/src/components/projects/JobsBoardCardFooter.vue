<template>
  <div
    class="jbf"
    :class="{ 'jbf--compact': compact }"
    :data-footer-state="footerState"
    :data-run-state="runState || undefined"
    :data-testid="compact ? 'jb-footer-compact' : 'jb-footer'"
  >
    <StagingControlArea
      v-if="areaPhase && !compact"
      variant="project"
      :phase="areaPhase"
      :mode="isExecutionModeLocked ? executionMode : executionPlatform"
      :mode-locked="isExecutionModeLocked"
      :stage-text="stageButtonText"
      :stage-title="stageButtonTitle"
      :stage-role="stageRole"
      :stage-needs-mode="stageNeedsMode"
      :stage-blocked="stageButtonDisabled"
      :stage-busy="loadingStageProject"
      :implement-ready="canImplement"
      :implement-busy="launching"
      :copying="copying"
      secondary-label="Jobs detail"
      @pick-mode="handleExecutionModeChange"
      @stage="onStage"
      @implement="onImplement"
      @copy-prompt="onCopyPrompt"
      @secondary="emit('open-detail', project)"
    >
      <template #trailing>
        <v-btn
          class="jb-icon-btn"
          size="small"
          variant="text"
          icon
          title="Go to this project's Hub thread"
          aria-label="Go to this project's Hub thread"
          data-testid="jb-btn-hub"
          @click="emit('open-hub', project)"
        >
          <v-icon size="18">mdi-forum</v-icon>
        </v-btn>
      </template>
    </StagingControlArea>

    <div v-else class="jbf-row">
      <v-btn
        v-if="compact && areaPhase === 'pickup'"
        class="jb-btn jb-btn-primary"
        size="small"
        variant="flat"
        :loading="copying"
        data-testid="sca-copy-prompt"
        @click="onCopyPrompt"
      >
        <v-icon start size="16" aria-hidden="true">mdi-content-copy</v-icon>
        Copy prompt
      </v-btn>

      <span v-if="runState === 'quiet'" class="jbf-quiet" data-testid="jbf-quiet-chip">Quiet</span>

      <v-btn
        v-if="footerState === 'review'"
        class="jb-btn jb-btn-review"
        size="small"
        variant="flat"
        data-testid="jb-btn-review"
        @click="emit('review', project)"
      >
        Review project
      </v-btn>

      <v-btn
        v-if="!compact || (footerState === 'implementing' && areaPhase !== 'pickup')"
        class="jb-btn jb-btn-ghost"
        size="small"
        variant="text"
        data-testid="jb-btn-detail"
        @click="emit('open-detail', project)"
      >
        Jobs detail
      </v-btn>

      <span v-if="!compact" class="jbf-spacer" />
      <v-btn
        v-if="!compact"
        class="jb-icon-btn"
        size="small"
        variant="text"
        icon
        title="Go to this project's Hub thread"
        aria-label="Go to this project's Hub thread"
        data-testid="jb-btn-hub"
        @click="emit('open-hub', project)"
      >
        <v-icon size="18">mdi-forum</v-icon>
      </v-btn>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useProjectStageControls } from '@/composables/useProjectStageControls'
import { copyImplementationPrompt, startChainMemberThenCopyPrompt } from '@/composables/usePlayButton'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'
import { needsInputOwner } from '@/utils/jobStatusWord'
import { isOrchestrator } from '@/utils/agentDisplay'
import StagingControlArea from '@/components/projects/StagingControlArea.vue'

const props = defineProps({
  project: {
    type: Object,
    required: true,
  },
  sectionLabel: {
    type: String,
    required: true,
  },
  agents: {
    type: Array,
    default: () => [],
  },
  showStaging: {
    type: Boolean,
    default: true,
  },
  chainTurn: {
    type: Boolean,
    default: false,
  },
  compact: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['open-detail', 'open-hub', 'changed', 'review'])

const {
  canImplement,
  readyToLaunch,
  launched,
  executionPlatform,
  executionMode,
  isExecutionModeLocked,
  stageNeedsMode,
  handleExecutionModeChange,
  isProjectStaging,
  isProjectStaged,
  canRestage,
  loadingStageProject,
  handleStageOrRestage,
  handleLaunchJobs,
  stageButtonText,
  stageButtonDisabled,
  stageButtonTitle,
} = useProjectStageControls({
  project: () => props.project,
  seedState: true,
})

const FINISHED_LABELS = new Set([JOBS_SECTION_LABELS.COMPLETE, JOBS_SECTION_LABELS.STOPPED])
const finished = computed(() => FINISHED_LABELS.has(props.sectionLabel))
const footerState = computed(() => {
  if (props.sectionLabel === JOBS_SECTION_LABELS.REVIEW) return 'review'
  if (finished.value) return 'implementing'
  if (launched.value) return 'implementing'
  if (readyToLaunch.value) return 'staged'
  return 'ready'
})

const NEEDS_KINDS = new Set(['decision', 'blocked'])
const runState = computed(() => {
  if (footerState.value === 'review' || finished.value) return null
  if (!launched.value && !props.chainTurn) return null
  const kind = needsInputOwner(props.agents)?.kind
  if (NEEDS_KINDS.has(kind)) return 'needs'
  if (kind === 'silent') return 'quiet'
  const orchestrator = props.agents.find(isOrchestrator)
  return !orchestrator || orchestrator.status === 'waiting' ? 'pickup' : 'running'
})

const areaPhase = computed(() => {
  if (runState.value === 'pickup' && (props.showStaging || props.chainTurn)) return 'pickup'
  if (!props.showStaging) return null
  if (footerState.value === 'ready' || footerState.value === 'staged') return footerState.value
  return null
})

const stageRole = computed(() => {
  if (isProjectStaging.value || isProjectStaged.value) return 'quiet'
  return canRestage.value ? 'secondary' : 'next'
})

const launching = ref(false)
const copying = ref(false)
const { copy: clipboardCopy } = useClipboard()
const { showToast } = useToast()

async function onStage() {
  await handleStageOrRestage()
  emit('changed', props.project)
}

async function onImplement() {
  launching.value = true
  try {
    await handleLaunchJobs()
  } finally {
    launching.value = false
  }
  emit('changed', props.project)
}

async function onCopyPrompt() {
  copying.value = true
  try {
    const projectId = props.project.id
    if (props.chainTurn) {
      await startChainMemberThenCopyPrompt({ projectId, clipboardCopy, showToast })
      emit('changed', props.project)
    } else {
      await copyImplementationPrompt({ projectId, executionMode: executionMode.value, clipboardCopy, showToast })
    }
  } finally {
    copying.value = false
  }
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jbf {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.jbf-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.jbf-spacer {
  margin-left: auto;
}

.jb-btn {
  font-size: 0.76rem;
  font-weight: 600;
  text-transform: none;
  letter-spacing: 0;
}

.jb-btn-primary {
  background: $color-brand-yellow;
  color: $color-background-primary;
}

.jbf-quiet {
  font-size: 0.68rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: $border-radius-pill;
  background: rgba($color-text-primary, 0.08);
  color: $color-text-secondary;
}

.jb-btn-review {
  background: $color-accent-success;
  color: $color-on-yellow-ink;
}

.jb-btn-ghost {
  color: $color-text-tertiary;
}

.jb-icon-btn {
  min-width: 36px;
}
</style>
