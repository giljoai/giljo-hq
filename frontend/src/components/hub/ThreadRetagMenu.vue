<!--
  ThreadRetagMenu.vue — FE-9530

  The ONLY way an old, pre-existing thread ever gets a product (operator ruling 2:
  no bulk migration). A menu rather than a v-select so it matches the thread
  header's icon-button language instead of introducing a form control there.

  Dumb: owns no store, emits `retag` with the chosen product id (or '' for
  "No product") and lets the caller do the actual write + toast, matching
  ThreadCard's "list-level state stays in the parent" boundary.
-->
<template>
  <v-menu>
    <template #activator="{ props: menuProps }">
      <button
        type="button"
        class="thread-retag-menu__trigger"
        title="Retag product"
        aria-label="Retag this thread's product"
        data-testid="thread-header-retag"
        v-bind="menuProps"
      >
        <v-icon size="14">mdi-cube-outline</v-icon>
        {{ productLabel }}
      </button>
    </template>
    <v-list density="compact" data-testid="thread-header-retag-menu">
      <v-list-item title="No product" data-testid="thread-header-retag-clear" @click="$emit('retag', '')" />
      <v-list-item
        v-for="p in products"
        :key="p.id"
        :title="p.name"
        :data-testid="`thread-header-retag-${p.id}`"
        @click="$emit('retag', p.id)"
      />
    </v-list>
  </v-menu>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  productId: { type: String, default: null },
  products: { type: Array, default: () => [] },
})
defineEmits(['retag'])

const productLabel = computed(() => {
  if (!props.productId) return 'No product'
  return props.products.find((p) => p.id === props.productId)?.name || 'Product'
})
</script>

<style scoped lang="scss">
.thread-retag-menu__trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.75rem; // 12
  font-family: 'IBM Plex Mono', monospace;
  transition: color 0.15s ease, background 0.15s ease;

  &:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.08);
  }
}
</style>
