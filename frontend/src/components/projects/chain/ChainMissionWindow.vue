<template>
  <div class="chain-mission-window smooth-border" data-testid="chain-mission-window">
    <div class="chain-mission-window__label">
      <span>Multi project mission</span>
    </div>
    <div class="chain-mission-window__body scrollbar-standard">
      <EmptyState
        v-if="!mission"
        icon="mdi-file-document-outline"
        title="No overarching mission yet"
        compact
      />
      <template v-else>
        <span class="chain-mission-window__tag">
          <v-icon size="14" class="mr-1">mdi-creation</v-icon>
          Conductor Generated
        </span>
        <div class="chain-mission-window__content">{{ mission }}</div>
      </template>
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

.chain-mission-window {
  display: flex;
  flex-direction: column;
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  padding: 16px 20px;
  margin-bottom: 16px;
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

  &__tag {
    display: inline-flex;
    align-items: center;
    background: rgba($color-agent-orchestrator, 0.15);
    color: $color-agent-orchestrator;
    font-size: 0.65rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: $border-radius-default;
    margin-bottom: 8px;
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
