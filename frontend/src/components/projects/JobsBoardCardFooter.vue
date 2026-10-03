<template>
  <div class="jbf" :class="{ 'jbf--compact': compact }" :data-footer-state="footerState" :data-testid="compact ? 'jb-footer-compact' : 'jb-footer'">
    <div
      v-if="!compact && showStaging && footerState === 'ready'"
      class="jbf-mode-row"
      :class="{ 'jbf-mode-row--refused': modeRefused, 'jbf-mode-row--picked': executionModeSelected }"
      data-testid="jbf-mode-row"
    >
      <RunAsSwitch
        :model-value="executionPlatform"
        :locked="isExecutionModeLocked"
        :refused="modeRefused"
        data-testid="jbf-run-as"
        @change="handleExecutionModeChange"
      />
      <HarnessChip :harness="detectedHarness" />
      <span v-if="modeRefused" class="jbf-mode-refusal" role="alert" data-testid="jbf-mode-refusal">
        Pick a mode before staging.
      </span>
    </div>

    <div class="jbf-row">
      <span
        v-if="!compact && footerState === 'staged' && modeLabel"
        class="jbf-mode-tag"
        data-testid="jbf-mode-tag"
      >
        <v-icon size="12" aria-hidden="true">mdi-lock</v-icon>
        {{ modeLabel }}
      </span>

      <v-btn
        v-if="showStaging && footerState === 'staged'"
        class="jb-btn jb-btn-primary"
        size="small"
        variant="flat"
        :disabled="!canImplement || launching"
        :loading="launching"
        data-testid="jbf-implement"
        @click="onImplement"
      >
        <v-icon start size="16" aria-hidden="true">mdi-play</v-icon>
        Implement
      </v-btn>

      <v-btn
        v-if="showStaging && (footerState === 'ready' || footerState === 'staged')"
        class="jb-btn"
        :class="stageButtonClass"
        size="small"
        :variant="stageButtonVariant"
        :loading="loadingStageProject"
        :disabled="stageButtonDisabled"
        :title="stageButtonTitle"
        data-testid="jbf-stage"
        @click="onStage"
      >
        {{ stageButtonText }}
      </v-btn>

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
        v-if="!compact || footerState === 'implementing'"
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
import { computed, ref, watchEffect } from 'vue'
import { useProjectStageControls } from '@/composables/useProjectStageControls'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'
import { JOBS_SECTION_LABELS } from '@/utils/jobsSectionLabel'
import HarnessChip from '@/components/projects/project-tabs/HarnessChip.vue'
import RunAsSwitch from '@/components/projects/RunAsSwitch.vue'


const props = defineProps({
  project: {
    type: Object,
    required: true,
  },
  sectionLabel: {
    type: String,
    required: true,
  },
  showStaging: {
    type: Boolean,
    default: true,
  },
  compact: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['open-detail', 'open-hub', 'changed', 'review'])

const harnessWanted = ref(false)

const {
  detectedHarness,
  canImplement,
  readyToLaunch,
  launched,
  executionPlatform,
  executionMode,
  executionModeSelected,
  isExecutionModeLocked,
  modeRefused,
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
  loadHarness: () => harnessWanted.value,
})

const FINISHED_LABELS = new Set([JOBS_SECTION_LABELS.COMPLETE, JOBS_SECTION_LABELS.STOPPED])
const footerState = computed(() => {
  if (props.sectionLabel === JOBS_SECTION_LABELS.REVIEW) return 'review'
  if (FINISHED_LABELS.has(props.sectionLabel)) return 'implementing'
  if (launched.value) return 'implementing'
  if (readyToLaunch.value) return 'staged'
  return 'ready'
})

watchEffect(() => {
  harnessWanted.value = props.showStaging && footerState.value === 'ready'
})

const modeLabel = computed(() => {
  const mode = executionMode.value
  if (!mode) return ''
  return isSubagentExecutionMode(mode) ? 'Subagent' : 'Multi-Terminal'
})

const stageLook = computed(() => {
  if (isProjectStaging.value || isProjectStaged.value) return 'ghost'
  return canRestage.value ? 'secondary' : 'primary'
})
const stageButtonClass = computed(() => `jb-btn-${stageLook.value}`)
const stageButtonVariant = computed(
  () => ({ primary: 'flat', secondary: 'outlined', ghost: 'text' })[stageLook.value],
)

const launching = ref(false)

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
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jbf {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.jbf-mode-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 2px 0;
}

.jbf-mode-refusal {
  margin-left: auto;
  font-size: 0.72rem;
  font-weight: 500;
  color: $color-status-warning;
}

.jbf-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.jbf-mode-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.68rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: $border-radius-pill;
  background: rgba(var(--v-theme-on-surface), 0.08);
  color: var(--text-secondary);
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
  color: $color-on-yellow-ink;
}

.jb-btn-secondary {
  color: $color-brand-yellow;
  border-color: $color-brand-yellow;
  border-width: 2px;
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
