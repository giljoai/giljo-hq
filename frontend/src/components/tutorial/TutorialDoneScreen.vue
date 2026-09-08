<template>
  <div class="done-screen">
    <img src="/icons/Giljo_YW_Face.svg" alt="" class="done-face" />
    <h2 class="done-title">Great work, you just added a product. Time to put your agents to work.</h2>
    <!-- FE-9569 Part 4: the old copy promised "four read-only audits that
         seed your 360 Memory" as though that already happened (it had not),
         alongside a lookalike card that didn't match what the user then
         found on Home. Reconciled against the REAL Home quick-launch logic
         (WelcomeView.vue's quickCards computed): right after this tour
         finishes -- active product, zero projects -- Home shows exactly
         newProjectCard + PROJECT_TEMPLATES' two cards. Described in prose
         instead of rendering a second lookalike card (operator's own
         stated alternative). -->
    <p class="done-sub">
      Your Home screen will now show three cards: create your first project, bootstrap a new
      product, and import an existing product. We suggest Import an existing product — it
      creates a few seed projects to get you going, and writes your first 360 memories.
    </p>

    <!-- FE-9320: the finish state needs its own way out. Until now the only exit
         from a COMPLETED tutorial was the footer's "Skip - I'll explore on my
         own", which reads as abandoning the tour you just finished. -->
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
  /** Router door choice -- kept for API compatibility with callers, but no
   *  longer drives per-door copy (FE-9569 Part 4: the message is the same
   *  regardless of which door produced the product). */
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
