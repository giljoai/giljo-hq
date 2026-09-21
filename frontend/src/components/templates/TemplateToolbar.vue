<template>
  <div class="filter-bar">
    <v-text-field
      v-model="search"
      prepend-inner-icon="mdi-magnify"
      placeholder="Search templates..."
      variant="solo"
      density="compact"
      clearable
      hide-details
      flat
      class="filter-search"
    />
    <v-select
      v-model="filterRole"
      :items="availableRoles"
      placeholder="Role"
      clearable
      variant="solo"
      flat
      density="compact"
      hide-details
      class="filter-select"
    />
    <v-select
      v-model="filterStatus"
      :items="statusOptions"
      placeholder="Status"
      clearable
      variant="solo"
      flat
      density="compact"
      hide-details
      class="filter-select"
    />
    <v-select
      v-model="scopeMode"
      :items="SCOPE_OPTIONS"
      variant="solo"
      flat
      density="compact"
      hide-details
      aria-label="Which products to list agents from"
      class="filter-select filter-scope"
      data-testid="show-all-products"
    />
    <v-btn
      variant="tonal"
      prepend-icon="mdi-cog-outline"
      title="Agent behaviour settings"
      aria-label="Agent behaviour settings"
      data-testid="agent-behaviour-button"
      @click="emit('open-behaviour')"
    >
      Behaviour
      <v-chip
        v-if="behaviourChangedCount > 0"
        size="x-small"
        color="primary"
        variant="flat"
        class="ml-2"
        data-testid="agent-behaviour-badge"
      >
        {{ behaviourChangedCount }}
      </v-chip>
    </v-btn>
    <v-menu>
      <template #activator="{ props: menuProps }">
        <v-btn
          v-bind="menuProps"
          icon="mdi-dots-vertical"
          variant="tonal"
          size="small"
          title="Bulk actions for this product"
          aria-label="Bulk actions for this product"
          data-testid="product-bulk-menu"
          :disabled="!canBulk && !canCreate"
          :loading="bulkRunning"
        />
      </template>
      <v-list density="compact" min-width="240">
        <v-list-item
          prepend-icon="mdi-check-all"
          title="Enable all for this product"
          data-testid="bulk-enable-product"
          :disabled="!canBulk"
          @click="emit('bulk-set-all', true)"
        />
        <v-list-item
          prepend-icon="mdi-close-box-multiple-outline"
          title="Disable all for this product"
          data-testid="bulk-disable-product"
          :disabled="!canBulk"
          @click="emit('bulk-set-all', false)"
        />
        <v-divider class="my-1" />
        <v-list-item
          prepend-icon="mdi-account-multiple-plus"
          title="Add default agents"
          data-testid="add-default-agents"
          :disabled="!canCreate"
          @click="emit('add-defaults')"
        />
      </v-list>
    </v-menu>
    <v-btn
      icon="mdi-plus"
      color="primary"
      variant="flat"
      size="small"
      title="New template"
      aria-label="Create new template"
      data-testid="new-template"
      :disabled="!canCreate"
      @click="emit('create')"
    />
  </div>
</template>

<script setup>
const search = defineModel('search', { type: String, default: '' })
const filterRole = defineModel('filterRole', { type: String, default: null })
const filterStatus = defineModel('filterStatus', { type: String, default: null })
const scopeMode = defineModel('scopeMode', { type: String, default: 'product' })

defineProps({
  availableRoles: { type: Array, default: () => [] },
  statusOptions: { type: Array, default: () => [] },
  behaviourChangedCount: { type: Number, default: 0 },
  canBulk: { type: Boolean, default: false },
  canCreate: { type: Boolean, default: false },
  bulkRunning: { type: Boolean, default: false },
})

const emit = defineEmits(['open-behaviour', 'bulk-set-all', 'add-defaults', 'create'])

const SCOPE_OPTIONS = [
  { title: 'This product', value: 'product' },
  { title: 'All products', value: 'all' },
]
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

/* 0873: filter bar layout (matches TasksView pattern) */
/* FE-9616: STICKY. The roster runs long -- longer still with the scope set to
   every product -- and search, scope and the actions belong to the list you are
   scrolling. `--v-layout-top` is the height Vuetify reserves for the app bar, so
   the bar parks directly under the product tab strip when one is open and at the
   top of the viewport when none is. */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  position: sticky;
  top: var(--v-layout-top, 0px);
  z-index: 3;
  padding: 8px 0;
  background: rgb(var(--v-theme-background));
}

.filter-search {
  flex: 1;
}

.filter-search :deep(.v-field) {
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
  border-radius: $border-radius-default;
}

.filter-search :deep(.v-field:focus-within) {
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.3);
}

.filter-select {
  flex: 0 0 160px;
}

.filter-select :deep(.v-field) {
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
  border-radius: $border-radius-default;
}

/* Wide enough for "This product" and "All products" to render whole. */
.filter-scope {
  flex: 0 0 170px;
}

@media (max-width: 960px) {
  .filter-bar {
    flex-wrap: wrap;
  }
  .filter-search {
    max-width: 100%;
  }
}
</style>
