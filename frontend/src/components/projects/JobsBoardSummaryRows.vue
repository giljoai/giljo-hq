<template>
  <div class="jb-sum" data-testid="jb-summary-rows">
    <div class="jb-srow" data-testid="jb-row-description">
      <span class="jb-srow-k">Description</span>
      <span class="jb-srow-v" :class="{ 'jb-srow-v--placeholder': !descriptionLine }">
        <span class="jb-ell">{{ descriptionLine || 'No description yet.' }}</span>
      </span>
      <button
        type="button"
        class="jb-pen"
        title="Edit description"
        aria-label="Edit description"
        data-testid="jb-edit-description"
        @click="emit('edit-description', project)"
      >
        <v-icon size="13">mdi-pencil</v-icon>
      </button>
    </div>

    <div class="jb-srow" data-testid="jb-row-mission">
      <span class="jb-srow-k">Mission</span>
      <span class="jb-srow-v" :class="{ 'jb-srow-v--placeholder': missionState === 'none' }">
        <span class="jb-dot" :class="`jb-dot--${missionState}`" data-testid="jb-mission-state" :data-state="missionState" aria-hidden="true" />
        <span v-if="missionState === 'writing'" class="jb-state-word">Orchestrator writing<LiveDots /></span>
        <span v-else-if="missionState === 'written'" class="jb-state-word">Written</span>
        <span class="jb-ell">{{ missionLine }}</span>
      </span>
      <span class="jb-pen-gap" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import LiveDots from './LiveDots.vue'
import { firstLine } from '@/utils/firstLine'

const props = defineProps({
  project: { type: Object, required: true },
  mission: { type: String, default: '' },
  missionState: { type: String, default: 'none' },
  chainMember: { type: Boolean, default: false },
})

const emit = defineEmits(['edit-description'])

const descriptionLine = computed(() => firstLine(props.project?.description))

const missionLine = computed(() => {
  if (props.missionState === 'none') {
    return props.chainMember
      ? 'Written when the chain reaches this step.'
      : 'No mission yet. Press Stage and the orchestrator writes it.'
  }
  return firstLine(props.mission)
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-sum {
  display: flex;
  flex-direction: column;
  border-radius: $border-radius-md;
  box-shadow: inset 0 0 0 1px $color-border-tertiary;
  overflow: hidden;
  margin-bottom: 8px;
}

.jb-srow {
  display: grid;
  grid-template-columns: 86px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 5px 8px 5px 12px;
  min-height: 36px;
  min-width: 0;

  & + & {
    box-shadow: inset 0 1px 0 0 $color-border-tertiary;
  }
}

.jb-srow-k {
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: $color-text-secondary;
}

.jb-srow-v {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  color: $color-text-tertiary;
  white-space: nowrap;
  overflow: hidden;

  &--placeholder {
    color: $color-text-secondary;
    font-style: italic;
  }
}

.jb-ell {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.jb-state-word {
  flex: none;
  color: $color-text-primary;
  font-weight: 500;
  font-style: normal;
}

.jb-dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: $color-text-secondary;

  &--none {
    background: none;
    box-shadow: inset 0 0 0 1.5px $color-text-secondary;
  }

  &--writing {
    background: $color-status-waiting;
    animation: jb-pulse 1.4s ease-in-out infinite;
  }

  &--written {
    background: $color-status-complete;
  }
}

@keyframes jb-pulse {
  50% {
    opacity: 0.35;
  }
}

@media (prefers-reduced-motion: reduce) {
  .jb-dot--writing {
    animation: none;
  }
}

.jb-pen {
  flex: none;
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: $border-radius-sharp;
  background: none;
  border: 0;
  padding: 0;
  color: $color-text-tertiary;
  cursor: pointer;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
    background: rgba($color-brand-yellow, 0.08);
  }
}

.jb-pen-gap {
  width: 24px;
}
</style>
