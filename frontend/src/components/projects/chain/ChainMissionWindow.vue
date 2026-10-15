<template>
  <div class="chain-mission">
    <div v-if="mission || $slots.actions" class="chain-mission__row" data-testid="chain-mission-row">
      <span v-if="mission" class="chain-mission__tag" data-testid="chain-mission-tag">
        <v-icon size="14" class="mr-1">mdi-creation</v-icon>
        Conductor Generated
      </span>
      <div v-if="$slots.actions" class="chain-mission__actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="chain-mission-window smooth-border" data-testid="chain-mission-window">
      <div class="chain-mission-window__label">
        <span>Chain goal</span>
      </div>
      <div class="chain-mission-window__body scrollbar-standard">
        <EmptyState
          v-if="!mission"
          icon="mdi-file-document-outline"
          title="No chain goal yet"
          compact
        />
        <div v-else class="chain-mission-window__content">{{ mission }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import EmptyState from '@/components/common/EmptyState.vue'

defineProps({
  mission: {
    type: String,
    default: '',
  },
})
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.chain-mission {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  margin-bottom: 16px;

  // The badge left, the host's actions right; wraps on a narrow group.
  &__row {
    align-self: stretch;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 12px;
    margin-bottom: 8px;
  }

  &__tag {
    display: inline-flex;
    align-items: center;
    background: rgba($color-agent-orchestrator, 0.15);
    color: $color-agent-orchestrator;
    font-size: 0.65rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: $border-radius-default;
  }

  &__actions {
    display: inline-flex;
    align-items: center;
    margin-left: auto;
  }
}

.chain-mission-window {
  align-self: stretch;
  display: flex;
  flex-direction: column;
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  padding: 16px 20px;
  max-height: 180px;

  &__label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    color: $color-text-muted;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600;
    margin-bottom: 8px;
  }

  &__body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }

  &__content {
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 0.78rem;
    line-height: 1.5;
    color: $color-text-secondary;
    font-style: italic;
  }
}
</style>
