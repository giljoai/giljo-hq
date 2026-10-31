<template>
  <div
    ref="stripEl"
    class="product-tab-strip"
    role="tablist"
    aria-label="Open products"
    data-testid="product-tab-strip"
  >
    <div
      v-if="showAll"
      ref="allEl"
      class="product-tab product-tab--all smooth-border"
      :class="{ 'product-tab--active': allSelected }"
    >
      <button
        type="button"
        role="tab"
        class="product-tab__select"
        :aria-selected="allSelected"
        title="Every product"
        data-testid="product-tab-all"
        @click="emit('select-all')"
      >
        All
      </button>
    </div>
    <div
      v-for="tab in visibleTabs"
      :key="tab.id"
      class="product-tab smooth-border"
      :class="{ 'product-tab--active': isViewed(tab) }"
    >
      <button
        type="button"
        role="tab"
        class="product-tab__select"
        :aria-selected="isViewed(tab)"
        :data-testid="`product-tab-${tab.id}`"
        :title="tab.name"
        @click="emit('select', tab.id)"
      >
        {{ tab.name }}
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

    <v-menu v-if="overflowTabs.length">
      <template #activator="{ props: menuProps }">
        <button
          type="button"
          class="product-tab__more smooth-border"
          :aria-label="`${overflowTabs.length} more open products`"
          data-testid="product-tab-more"
          v-bind="menuProps"
        >
          +{{ overflowTabs.length }} more
          <v-icon size="14">mdi-chevron-down</v-icon>
        </button>
      </template>
      <v-list density="compact" data-testid="product-tab-more-menu">
        <v-list-item
          v-for="tab in overflowTabs"
          :key="tab.id"
          :title="tab.name"
          :data-testid="`product-tab-more-${tab.id}`"
          @click="emit('select', tab.id)"
        >
          <template #append>
            <v-btn
              icon="mdi-close"
              size="x-small"
              variant="text"
              :aria-label="`Close ${tab.name} tab`"
              data-testid="product-tab-more-close"
              @click.stop="emit('close', tab.id)"
            />
          </template>
        </v-list-item>
      </v-list>
    </v-menu>

    <v-menu v-if="addableProducts.length">
      <template #activator="{ props: menuProps }">
        <button
          ref="addEl"
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

    <div ref="measureEl" class="product-tab-strip__measure" aria-hidden="true" inert>
      <div v-for="tab in tabs" :key="tab.id" class="product-tab smooth-border" data-measure-tab>
        <span class="product-tab__select">{{ tab.name }}</span>
        <span v-if="tabs.length > 1" class="product-tab__close"><v-icon size="14">mdi-close</v-icon></span>
      </div>
      <span class="product-tab__more smooth-border" data-measure-more>
        +{{ tabs.length }} more <v-icon size="14">mdi-chevron-down</v-icon>
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { planTabFit } from './productTabFit'
const props = defineProps({
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
  showAll: {
    type: Boolean,
    default: false,
  },
  allSelected: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['select', 'close', 'add', 'select-all'])

const GAP = 6
const stripEl = ref(null)
const measureEl = ref(null)
const allEl = ref(null)
const addEl = ref(null)
const shownIndexes = ref(null)

function isViewed(tab) {
  return !props.allSelected && tab.id === props.viewedId
}

const visibleTabs = computed(() =>
  shownIndexes.value ? shownIndexes.value.map((i) => props.tabs[i]).filter(Boolean) : props.tabs,
)
const overflowTabs = computed(() => {
  const shown = new Set(visibleTabs.value.map((t) => t.id))
  return props.tabs.filter((t) => !shown.has(t.id))
})

function measure() {
  const strip = stripEl.value
  const box = measureEl.value
  if (!strip || !box) return
  const widths = [...box.querySelectorAll('[data-measure-tab]')].map((el) => el.offsetWidth)
  const more = box.querySelector('[data-measure-more]')
  const fixedWidth =
    (allEl.value ? allEl.value.offsetWidth + GAP : 0) + (addEl.value ? addEl.value.offsetWidth + GAP : 0)
  shownIndexes.value = planTabFit({
    available: strip.clientWidth,
    widths,
    gap: GAP,
    fixedWidth,
    moreWidth: more ? more.offsetWidth : 0,
    viewedIndex: props.tabs.findIndex((t) => t.id === props.viewedId),
  })
}

let observer = null
onMounted(() => {
  measure()
  observer = new ResizeObserver(() => measure())
  if (stripEl.value) observer.observe(stripEl.value)
})
onBeforeUnmount(() => observer?.disconnect())
watch(
  () => [props.tabs.map((t) => t.name).join('\n'), props.viewedId, props.showAll, props.addableProducts.length],
  () => nextTick(measure),
)
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.product-tab-strip {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  width: 100%;
  min-width: 0;
  overflow: hidden;
}

.product-tab-strip__measure {
  position: absolute;
  top: 0;
  left: 0;
  display: flex;
  gap: 6px;
  visibility: hidden;
  pointer-events: none;
}

.product-tab--all {
  border-style: dashed;

  &.product-tab--active {
    border-style: solid;
  }
}

.product-tab {
  display: flex;
  flex-shrink: 0;
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
  min-height: 30px;
  padding: 0 12px;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.product-tab__close {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  min-height: 30px;
  padding-right: 4px;
  border: none;
  background: transparent;
  color: inherit;
  opacity: 0.65;
  cursor: pointer;

  &:hover {
    opacity: 1;
  }
}

.product-tab__more {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 2px;
  min-height: 30px;
  padding: 0 10px 0 12px;
  border-radius: $border-radius-pill;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 0.75rem;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  --smooth-border-color: rgba(var(--v-theme-on-surface), 0.15);

  &:hover {
    --smooth-border-color: rgba(var(--v-theme-on-surface), 0.25);
  }
}

.product-tab__add {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  min-width: 30px;
  min-height: 30px;
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
