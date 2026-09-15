<template>
  <div class="empty-state" :class="{ 'empty-state--compact': compact }">
    <v-icon :icon="icon" :size="compact ? 24 : 48" class="empty-state-icon" />
    <div class="empty-state-title">{{ title }}</div>
    <div v-if="description" class="empty-state-description">{{ description }}</div>
    <div v-if="$slots.default" class="empty-state-actions"><slot /></div>
  </div>
</template>

<script setup>
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
.empty-state-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}
</style>
