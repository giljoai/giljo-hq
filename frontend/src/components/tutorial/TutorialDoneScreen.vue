<template>
  <div class="done-screen">
    <img src="/icons/Giljo_YW_Face.svg" alt="" class="done-face" />
    <h2 class="done-title">Great work, you just added a product. Time to put your agents to work.</h2>
    <p class="done-sub">
      Your Home screen will now show three cards: create your first project, bootstrap a new
      product, and import an existing product. We suggest Import an existing product — it
      creates a few seed projects to get you going, and writes your first 360 memories.
    </p>

    <v-btn
      color="primary"
      variant="flat"
      class="done-btn"
      data-testid="tutorial-done-close"
      append-icon="mdi-arrow-right"
      @click="$emit('close')"
    >
      Go to my dashboard
    </v-btn>
  </div>
</template>

<script setup>
defineProps({
  routerChoice: {
    type: String,
    default: null,
  },
})

defineEmits(['close'])
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.done-screen {
  display: flex;
  flex-direction: column;
  height: 100%;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 16px;
}

.done-face {
  height: 40px;
}

.done-title {
  margin: 0;
  max-width: 480px;
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 28px;
  letter-spacing: -0.02em;
  color: $color-text-primary;
}

.done-sub {
  margin: 0;
  max-width: 460px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.done-btn {
  margin-top: 4px;
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  border-radius: $border-radius-default;
  background: $color-brand-yellow !important;
  color: $color-on-yellow-ink !important;

  &:hover {
    background: $color-brand-yellow-hover !important;
  }
}
</style>
