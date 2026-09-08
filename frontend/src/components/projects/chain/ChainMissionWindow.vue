<template>
  <!-- FE-6174b: the wide overarching "Multi project mission" window (slide 5).
       Shows the head project's mission field (OD-4 — no new schema); live-fills
       over WebSocket exactly like the solo mission. Conditional layer only. -->
  <div class="chain-mission-window smooth-border" data-testid="chain-mission-window">
    <div class="chain-mission-window__label">
      <span>Multi project mission</span>
    </div>
    <div class="chain-mission-window__body scrollbar-standard">
      <!-- FE-9538 (Ask 3): compact -- this window caps at max-height:180px,
           and EmptyState's default (full-page) padding+icon budget clipped
           against that cap. See EmptyState.vue's doc comment for the root
           cause. -->
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
/**
 * ChainMissionWindow — FE-6174b
 * The chain-level overarching mission, stored on the head project's mission
 * field. Pure display; the host supplies the live value. Design-token only.
 */
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
