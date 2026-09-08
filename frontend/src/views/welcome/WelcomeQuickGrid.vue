<template>
  <div class="quick-grid">
    <div
      v-for="(card, i) in cards"
      :key="card.id || card.title"
      class="quick-card smooth-border"
      :class="{
        'quick-card--attention': card.attention,
        'quick-card--template': card.isTemplate,
        'quick-card--busy': card.busy,
      }"
      :style="{ '--card-accent': card.accent, animationDelay: (0.15 + i * 0.07) + 's' }"
      :data-template-id="card.templateId || null"
      @click="$emit('card-click', card)"
    >
      <div
        class="quick-card-icon"
        :style="{ background: card.iconBg, color: card.iconColor }"
      >
        <v-icon size="20">{{ card.icon }}</v-icon>
      </div>
      <div class="quick-card-title">{{ card.title }}</div>
      <div class="quick-card-desc">{{ card.description }}</div>
      <div v-if="card.subtitle" class="quick-card-subtitle">{{ card.subtitle }}</div>
      <span v-if="card.badge" class="quick-card-badge">{{ card.badge }}</span>
      <span v-if="card.busy" class="quick-card-busy-label">Creating…</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  cards: {
    type: Array,
    required: true,
  },
})

defineEmits(['card-click'])
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

/* ═══ QUICK LAUNCH ═══ */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 36px;

  // Single card during onboarding — center it
  &:has(.quick-card:only-child) {
    grid-template-columns: 1fr;
    max-width: 320px;
    margin-left: auto;
    margin-right: auto;
  }
}

.quick-card {
  background: rgb(var(--v-theme-surface));
  border-radius: $border-radius-rounded;
  padding: 20px;
  cursor: pointer;
  transition: all $transition-normal;
  position: relative;
  overflow: hidden;
  animation: fadeSlideUp 0.45s ease-out both;
}

.quick-card:hover {
  transform: translateY(-3px);
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255,255,255,0.10)), 0 10px 20px -6px rgba(0,0,0,0.25);
}

.quick-card--attention {
  animation: fadeSlideUp 0.45s ease-out both, attentionNudge 2.8s ease-in-out 1.2s infinite;
}

.quick-card--attention::before {
  opacity: 1;
}

.quick-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--card-accent, rgba(255,255,255,0.10));
  opacity: 0;
  transition: opacity $transition-normal;
}

.quick-card:hover::before {
  opacity: 1;
}

.quick-card-icon {
  width: 40px;
  height: 40px;
  border-radius: $border-radius-default;
  display: grid;
  place-items: center;
  margin-bottom: 12px;
}

.quick-card-title {
  font-size: 0.92rem;
  font-weight: 600;
  margin-bottom: 5px;
}

.quick-card-desc {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.4;
}

.quick-card-badge {
  display: block;
  text-align: center;
  margin-top: 10px;
  padding: 2px 8px;
  background: rgba(255,255,255,0.05);
  border-radius: $border-radius-sharp;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  color: var(--text-muted);
}

/* Step-4 starter-template cards */
.quick-card--template {
  --smooth-border-color: rgba(109, 179, 228, 0.28);
}

.quick-card--template .quick-card-subtitle {
  font-size: 0.7rem;
  color: var(--text-secondary); /* WCAG AA 6.56:1 on #12202e */
  margin-top: 8px;
  line-height: 1.35;
}

.quick-card--busy {
  opacity: 0.55;
  pointer-events: none;
}

.quick-card-busy-label {
  display: block;
  margin-top: 8px;
  font-size: 0.68rem;
  color: var(--text-muted); /* WCAG AA 4.98:1 */
  font-style: italic;
}

/* Keyframes used by quick-card animations — duplicated here because scoped
   styles don't cross component boundaries. */
@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes attentionNudge {
  0%, 100% {
    transform: translateY(0);
    box-shadow: inset 0 0 0 1px rgba(255, 195, 0, 0.18), 0 0 0 0 rgba(255, 195, 0, 0);
  }
  50% {
    transform: translateY(-2px);
    box-shadow: inset 0 0 0 1px rgba(255, 195, 0, 0.38), 0 0 18px -4px rgba(255, 195, 0, 0.22);
  }
}

/* ═══ RESPONSIVE ═══ */
// FE-9536: the old single 960px cutoff jumped straight from 3 columns to 1,
// skipping the whole tablet band (portrait ~768-834px, 16:9 landscape
// ~1024-1194px) where 3 cards could never fit but 1 wastes the width.
@media (max-width: $breakpoint-tablet) {
  .quick-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: $breakpoint-mobile) {
  .quick-grid {
    grid-template-columns: 1fr;
  }
}
</style>
