<template>
  <div class="chain-staging-actions">
    <v-btn
      class="stage-button"
      variant="outlined"
      :color="stageColor"
      :loading="staging"
      :disabled="stageDisabled"
      :title="stageTitle"
      data-testid="stage-chain-btn"
      @click="emit('stage')"
    >
      {{ stageText }}
    </v-btn>

    <v-btn
      class="launch-button"
      :disabled="!implementReady"
      :color="implementReady ? 'yellow-darken-2' : undefined"
      :variant="implementReady ? 'flat' : 'outlined'"
      data-testid="implement-chain-btn"
      @click="emit('implement')"
    >
      Implement
    </v-btn>
  </div>
</template>

<script setup>
defineProps({
  stageText: { type: String, default: '' },
  stageTitle: { type: String, default: '' },
  stageColor: { type: String, default: undefined },
  stageDisabled: { type: Boolean, default: false },
  staging: { type: Boolean, default: false },
  implementReady: { type: Boolean, default: false },
})

const emit = defineEmits(['stage', 'implement'])
</script>

<style scoped lang="scss">
.chain-staging-actions {
  display: contents;
}
</style>
