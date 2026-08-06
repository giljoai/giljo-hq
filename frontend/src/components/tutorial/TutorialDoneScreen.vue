<template>
  <div class="done-screen">
    <img src="/icons/Giljo_YW_Face.svg" alt="" class="done-face" />
    <h2 class="done-title">Product active. Time for a mission.</h2>
    <p class="done-sub">
      Your Home screen now shows this card. It creates a real project your agent runs — {{ cardSub }}
    </p>

    <div class="spotlight-card" data-testid="tutorial-spotlight-card">
      <v-icon size="26" class="spotlight-icon">{{ template.icon }}</v-icon>
      <div class="spotlight-text">
        <span class="spotlight-title">{{ template.cardTitle }}</span>
        <span class="spotlight-desc">Creates a staged project · you paste one prompt · agents do the rest</span>
      </div>
    </div>

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
import { computed } from 'vue'
import { PROJECT_TEMPLATES } from '@/composables/projectTemplates'

const props = defineProps({
  /** Router door choice — decides which bootstrap card gets the spotlight. */
  routerChoice: {
    type: String,
    default: null,
  },
})

defineEmits(['close'])

// D → import an existing product; A/B/C → bootstrap a new one. Labels and
// icons come from projectTemplates.js, the single source of truth.
const templateId = computed(() =>
  props.routerChoice === 'D' ? 'existing_product_bootstrap' : 'new_product_bootstrap',
)

const template = computed(
  () => PROJECT_TEMPLATES.find((t) => t.id === templateId.value) || PROJECT_TEMPLATES[0],
)

const cardSub = computed(() =>
  props.routerChoice === 'D'
    ? 'four read-only audits that seed your 360 Memory.'
    : 'a skeleton scaffold plus four starter dev projects.',
)
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
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 28px;
  letter-spacing: -0.02em;
  color: $color-text-primary;
}

.done-sub {
  margin: 0;
  max-width: 440px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.spotlight-card {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.5), 0 12px 40px rgba($color-brand-yellow, 0.12);
  padding: 20px 26px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.spotlight-icon {
  color: $color-brand-yellow;
}

.spotlight-text {
  display: flex;
  flex-direction: column;
  text-align: left;
}

.spotlight-title {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 16px;
  color: $color-text-primary;
}

.spotlight-desc {
  font-size: 12px;
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
