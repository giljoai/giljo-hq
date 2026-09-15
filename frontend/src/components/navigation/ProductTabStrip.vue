<template>
  <div class="product-tab-strip" role="tablist" aria-label="Open products" data-testid="product-tab-strip">
    <div
      v-for="tab in tabs"
      :key="tab.id"
      class="product-tab smooth-border"
      :class="{ 'product-tab--active': tab.id === viewedId }"
    >
      <button
        type="button"
        role="tab"
        class="product-tab__select"
        :aria-selected="tab.id === viewedId"
        :data-testid="`product-tab-${tab.id}`"
        :title="tab.name"
        @click="emit('select', tab.id)"
      >
        {{ tab.name }}
        <span
          v-if="tab.badgeCount > 0"
          class="product-tab__badge"
          :aria-label="`${tab.badgeCount} update${tab.badgeCount === 1 ? '' : 's'} on ${tab.name}`"
          data-testid="product-tab-badge"
        >
          {{ tab.badgeCount > 9 ? '9+' : tab.badgeCount }}
        </span>
      </button>
      <button
        v-if="tabs.length > 1"
        type="button"
        class="product-tab__close"
        :aria-label="`Close ${tab.name} tab`"
        data-testid="product-tab-close"
        @click.stop="emit('close', tab.id)"
      >
        <v-icon size="14">mdi-close</v-icon>
      </button>
    </div>

    <v-menu v-if="addableProducts.length">
      <template #activator="{ props: menuProps }">
        <button
          type="button"
          class="product-tab__add smooth-border"
          aria-label="Open another product in a new tab"
          data-testid="product-tab-add"
          v-bind="menuProps"
        >
          <v-icon size="16">mdi-plus</v-icon>
        </button>
      </template>
      <v-list density="compact" data-testid="product-tab-add-menu">
        <v-list-item
          v-for="product in addableProducts"
          :key="product.id"
          :title="product.name"
          :data-testid="`product-tab-add-${product.id}`"
          @click="emit('add', product.id)"
        />
      </v-list>
    </v-menu>
  </div>
</template>

<script setup>
defineProps({
  tabs: {
    type: Array,
    required: true,
  },
  viewedId: {
    type: String,
    default: '',
  },
  addableProducts: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['select', 'close', 'add'])
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.product-tab-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  width: 100%;
}

.product-tab {
  display: flex;
  align-items: stretch;
  border-radius: $border-radius-pill;
  overflow: hidden;
  color: var(--text-muted);
  transition: $transition-all-fast;
  --smooth-border-color: rgba(var(--v-theme-on-surface), 0.15);

  &:hover {
    color: var(--text-secondary);
    --smooth-border-color: rgba(var(--v-theme-on-surface), 0.25);
  }

  &--active,
  &--active:hover {
    background: rgba($color-brand-yellow, 0.12);
    color: $color-brand-yellow;
    --smooth-border-color: rgba(#{$color-brand-yellow}, 0.4);
  }
}

.product-tab__select {
  display: flex;
  align-items: center;
  min-height: 44px;
  padding: 0 16px;
  border: none;
  background: transparent;
  color: inherit;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-tab__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  margin-left: 6px;
  padding: 0 4px;
  border-radius: $border-radius-pill;
  background: $color-brand-yellow;
  color: var(--badge-text);
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 1;
}

.product-tab__close {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  min-height: 44px;
  border: none;
  background: transparent;
  color: inherit;
  opacity: 0.65;
  cursor: pointer;

  &:hover {
    opacity: 1;
  }
}

.product-tab__add {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  border-radius: $border-radius-pill;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: $transition-all-fast;
  --smooth-border-color: rgba(var(--v-theme-on-surface), 0.15);

  &:hover {
    color: var(--text-secondary);
    --smooth-border-color: rgba(var(--v-theme-on-surface), 0.25);
  }
}
</style>
