<template>
  <div class="empty-state" :class="{ 'empty-state--compact': compact }">
    <v-icon :icon="icon" :size="compact ? 24 : 48" class="empty-state-icon" />
    <div class="empty-state-title">{{ title }}</div>
    <div v-if="description" class="empty-state-description">{{ description }}</div>
  </div>
</template>

<script setup>
/**
 * FE-9538 (Ask 3): `compact` is opt-in and additive -- every existing caller
 * (LaunchTab.vue, TasksTable.vue) omits it and renders byte-identically.
 *
 * Root cause of the clipped conductor placeholder: ChainMissionWindow.vue
 * caps its body at max-height:180px, but this component's default
 * padding+icon+title budgets ~190px+ of content -- a full-page empty state
 * (this component's only prior use case) meeting a compact widget. The
 * operator's margin theory was close but not it; halving JUST the vertical
 * margin left the icon+title still too tall for the box. `compact` instead
 * shrinks the icon (48->24) and padding (48px 24px -> 16px 12px), the two
 * dimensions that actually drove the height over budget.
 */
defineProps({
  icon: { type: String, required: true },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  compact: { type: Boolean, default: false },
})
</script>

<style lang="scss" scoped>
@use '../../styles/design-tokens' as *;

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;

  &--compact {
    padding: 16px 12px;

    .empty-state-icon {
      margin-bottom: 8px;
    }

    .empty-state-title {
      margin-bottom: 0;
    }
  }
}
.empty-state-icon {
  color: $color-text-muted;
  margin-bottom: 16px;
  opacity: 0.6;
}
.empty-state-title {
  font-family: 'Outfit', sans-serif;
  font-size: 1rem;
  font-weight: 500;
  color: $color-text-secondary;
  margin-bottom: 8px;
}
.empty-state-description {
  font-size: 0.82rem;
  color: $color-text-muted;
  max-width: 400px;
  margin-bottom: 20px;
}
</style>
