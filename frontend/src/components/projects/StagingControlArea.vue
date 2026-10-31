<template>
  <section
    class="sca"
    :class="{
      'sca--attn': stageWaitsForMode,
      'sca--pulse': pulsing,
      'sca--highlight': highlighted,
    }"
    :data-phase="phase"
    :data-variant="variant"
    data-testid="staging-control-area"
    @animationend="pulsing = false"
  >
    <template v-if="phase === 'pickup'">
      <p class="sca-hint" data-testid="sca-pickup-hint">No agent has picked this up yet</p>
    </template>
    <template v-else>
      <span :id="labelId" class="sca-label" data-testid="sca-label">
        {{ modeLocked ? 'Execution mode' : 'Select execution mode' }}
      </span>
      <span v-if="modeLocked" class="sca-mode-tag" :data-testid="ids.modeTag">
        <v-icon size="12" aria-hidden="true">mdi-lock</v-icon>
        {{ modeLabel || 'Not picked' }}
      </span>
      <RunAsSwitch
        v-else
        :model-value="mode"
        :labelled-by="labelId"
        :data-testid="ids.runAs"
        @change="(picked) => emit('pick-mode', picked)"
      />
    </template>

    <div class="sca-row">
      <v-btn
        v-if="phase === 'pickup'"
        class="jb-btn jb-btn-primary"
        size="small"
        variant="flat"
        :loading="copying"
        data-testid="sca-copy-prompt"
        @click="emit('copy-prompt')"
      >
        <v-icon start size="16" aria-hidden="true">mdi-content-copy</v-icon>
        {{ variant === 'chain' ? 'Copy chain prompt' : 'Copy prompt' }}
      </v-btn>
      <template v-else>
        <v-btn
          class="jb-btn"
          :class="`jb-btn-${stageLook}`"
          size="small"
          :variant="LOOK_VARIANT[stageLook]"
          :loading="stageBusy"
          :disabled="stageBlocked"
          :aria-disabled="stageWaitsForMode ? 'true' : undefined"
          :aria-describedby="stageWaitsForMode ? reasonId : undefined"
          :title="stageWaitsForMode ? MODE_REASON : stageTitle"
          :data-testid="ids.stage"
          @click="onStage"
        >
          {{ stageText }}
        </v-btn>
        <v-btn
          class="jb-btn"
          :class="phase === 'staged' ? 'jb-btn-primary' : 'jb-btn-muted'"
          size="small"
          :variant="phase === 'staged' ? 'flat' : 'tonal'"
          :disabled="phase !== 'staged' || !implementReady || implementBusy"
          :loading="implementBusy"
          :data-testid="ids.implement"
          @click="emit('implement')"
        >
          <v-icon start size="16" aria-hidden="true">mdi-play</v-icon>
          {{ variant === 'chain' ? 'Implement chain' : 'Implement' }}
        </v-btn>
      </template>
      <slot name="actions" />
      <slot name="decision" />
      <span class="sca-spacer" />
      <button
        v-if="secondaryLabel"
        type="button"
        class="sca-link"
        :disabled="secondaryBusy"
        :aria-busy="secondaryBusy ? 'true' : undefined"
        :title="secondaryTitle || undefined"
        :data-testid="ids.secondary"
        @click="emit('secondary')"
      >
        {{ secondaryLabel }}
      </button>
      <slot name="trailing" />
    </div>

    <span v-if="stageWaitsForMode" :id="reasonId" class="sca-reason" data-testid="sca-mode-reason">
      {{ MODE_REASON }}
    </span>
  </section>
</template>

<script setup>
import { computed, ref, useId, watch } from 'vue'
import { isSubagentExecutionMode } from '@/composables/useExecutionMode'
import RunAsSwitch from '@/components/projects/RunAsSwitch.vue'

const props = defineProps({
  variant: { type: String, default: 'project' },
  phase: { type: String, required: true },
  mode: { type: String, default: null },
  modeLocked: { type: Boolean, default: false },
  stageText: { type: String, default: 'Stage' },
  stageTitle: { type: String, default: '' },
  stageRole: { type: String, default: 'next' },
  stageNeedsMode: { type: Boolean, default: false },
  stageBlocked: { type: Boolean, default: false },
  stageBusy: { type: Boolean, default: false },
  implementReady: { type: Boolean, default: false },
  implementBusy: { type: Boolean, default: false },
  copying: { type: Boolean, default: false },
  secondaryLabel: { type: String, default: '' },
  secondaryBusy: { type: Boolean, default: false },
  secondaryTitle: { type: String, default: '' },
})

const emit = defineEmits(['pick-mode', 'stage', 'implement', 'copy-prompt', 'secondary'])

const MODE_REASON = 'Pick a mode first'
const LOOK_VARIANT = { primary: 'flat', secondary: 'outlined', ghost: 'text', muted: 'tonal' }
const TEST_IDS = {
  project: { stage: 'jbf-stage', implement: 'jbf-implement', modeTag: 'jbf-mode-tag', runAs: 'jbf-run-as', secondary: 'jb-btn-detail' },
  chain: {
    stage: 'stage-chain-btn',
    implement: 'implement-chain-btn',
    modeTag: 'chain-group-mode-tag',
    runAs: 'chain-group-run-as',
    secondary: 'chain-group-deactivate',
  },
}

const uid = useId()
const labelId = `sca-label-${uid}`
const reasonId = `sca-reason-${uid}`
const ids = computed(() => TEST_IDS[props.variant] || TEST_IDS.project)

const modeLabel = computed(() => {
  if (!props.mode) return ''
  return isSubagentExecutionMode(props.mode) ? 'Subagent' : 'Multi-terminal'
})

const stageWaitsForMode = computed(() => props.phase === 'ready' && props.stageNeedsMode)

const stageLook = computed(() => {
  if (stageWaitsForMode.value) return 'muted'
  if (props.stageRole === 'quiet') return 'ghost'
  if (props.stageRole === 'secondary' || props.phase === 'staged') return 'secondary'
  return 'primary'
})

const pulsing = ref(false)
const highlighted = ref(false)

function prefersReducedMotion() {
  return typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches)
}

function onStage() {
  if (!stageWaitsForMode.value) {
    emit('stage')
    return
  }
  if (prefersReducedMotion()) {
    highlighted.value = true
  } else {
    pulsing.value = true
  }
}

watch(stageWaitsForMode, (waits) => {
  if (!waits) {
    pulsing.value = false
    highlighted.value = false
  }
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.sca {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border-radius: $border-radius-default;
  background: rgba($color-text-primary, 0.03);
  box-shadow: inset 0 0 0 1px $color-border-secondary;
  transition: box-shadow 0.18s;

  &--attn {
    box-shadow: inset 0 0 0 2px rgba($color-brand-yellow, 0.55);
  }

  &--highlight {
    box-shadow: inset 0 0 0 2px $color-brand-yellow;
    background: rgba($color-brand-yellow, 0.08);
  }

  &--pulse {
    animation: sca-pulse 0.6s ease-in-out 3;
  }
}

@keyframes sca-pulse {
  0%,
  100% {
    box-shadow: inset 0 0 0 2px rgba($color-brand-yellow, 0.55);
  }

  50% {
    box-shadow:
      inset 0 0 0 2px $color-brand-yellow,
      0 0 0 4px rgba($color-brand-yellow, 0.25);
  }
}

@media (prefers-reduced-motion: reduce) {
  .sca--pulse {
    animation: none;
  }
}

.sca-label {
  font-size: 0.72rem;
  font-weight: 600;
  color: $color-text-primary;
}

.sca-hint {
  margin: 0;
  font-size: 0.74rem;
  color: $color-text-secondary;
}

.sca-mode-tag {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.68rem;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: $border-radius-pill;
  background: rgba($color-text-primary, 0.08);
  color: $color-text-secondary;
}

.sca-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}

.sca-spacer {
  margin-left: auto;
}

.sca-reason {
  font-size: 0.72rem;
  color: $color-text-secondary;
}

.sca-link {
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-size: 0.76rem;
  color: $color-text-tertiary;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;

  &:hover:not(:disabled),
  &:focus-visible {
    color: $color-brand-yellow;
  }

  &:disabled {
    cursor: default;
    opacity: 0.7;
  }
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

.jb-btn-secondary {
  color: $color-brand-yellow;
  border-color: $color-brand-yellow;
  border-width: 2px;
}

.jb-btn-ghost {
  color: $color-text-tertiary;
}

.jb-btn-muted {
  color: $color-text-secondary;

  &[aria-disabled='true'] {
    cursor: not-allowed;
  }
}
</style>
