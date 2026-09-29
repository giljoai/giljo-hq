<template>
  <div class="chain-staging-actions">
    <v-btn
      class="stage-button jb-btn jb-btn-secondary"
      size="small"
      variant="outlined"
      :loading="staging"
      :disabled="stageDisabled"
      :title="stageTitle"
      data-testid="stage-chain-btn"
      @click="emit('stage')"
    >
      {{ stageText }}
    </v-btn>

    <v-btn
      class="launch-button jb-btn jb-btn-primary"
      size="small"
      variant="flat"
      :disabled="!implementReady"
      data-testid="implement-chain-btn"
      @click="emit('implement')"
    >
      <v-icon start size="16" aria-hidden="true">mdi-play</v-icon>
      Implement
    </v-btn>
  </div>
</template>

<script setup>
defineProps({
  stageText: { type: String, default: '' },
  stageTitle: { type: String, default: '' },
  stageDisabled: { type: Boolean, default: false },
  staging: { type: Boolean, default: false },
  implementReady: { type: Boolean, default: false },
})

const emit = defineEmits(['stage', 'implement'])
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.chain-staging-actions {
  display: contents;
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
</style>
