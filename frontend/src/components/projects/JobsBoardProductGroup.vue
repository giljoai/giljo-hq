<template>
  <section class="jb-pgroup" :class="{ 'jb-pgroup--folded': folded }" :data-product-id="group.id" data-testid="jobs-product-group">
    <div class="jb-pgroup-h">
      <button
        type="button"
        class="jb-pgroup-chev"
        :aria-expanded="!folded"
        :aria-label="`${folded ? 'Expand' : 'Collapse'} ${group.name}`"
        :title="folded ? 'Expand this product' : 'Collapse this product'"
        data-testid="jobs-product-group-fold"
        @click="emit('toggle', group.id)"
      >
        <v-icon size="14">{{ folded ? 'mdi-chevron-right' : 'mdi-chevron-down' }}</v-icon>
      </button>
      <span class="jb-pgroup-k">Product</span>
      <h2 class="jb-pgroup-name" data-testid="jobs-product-group-name">{{ group.name }}</h2>
      <span class="jb-pgroup-sum" data-testid="jobs-product-group-counts">
        {{ group.counts.staging }} staging · {{ group.counts.implementation }} implementing
      </span>
    </div>

    <div v-if="!folded" class="jb-pgroup-body">
      <p v-if="group.quiet" class="jb-pgroup-quiet" data-testid="jobs-product-group-quiet">
        {{ quietLine }}
      </p>
      <slot v-else />
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  group: {
    type: Object,
    required: true,
  },
  folded: {
    type: Boolean,
    default: false,
  },
  side: {
    type: String,
    default: 'implementation',
  },
})

const emit = defineEmits(['toggle'])

const quietLine = computed(() =>
  props.side === 'staging'
    ? 'Nothing waiting to stage. Switch to Implementation to see what runs.'
    : 'Nothing implementing. Switch to Staging to see what waits.',
)
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-pgroup {
  margin-bottom: 36px;
}

.jb-pgroup-h {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid $color-border-secondary;
}

.jb-pgroup--folded .jb-pgroup-h {
  border-bottom-color: $color-border-tertiary;
  margin-bottom: 0;
}

.jb-pgroup-chev {
  flex: none;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  background: none;
  border: 1px solid $color-border-secondary;
  border-radius: $border-radius-sharp;
  color: $color-text-secondary;
  cursor: pointer;
  padding: 0;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
    border-color: $color-brand-yellow;
  }
}

.jb-pgroup-k {
  font-size: 0.62rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: $color-text-secondary;
}

.jb-pgroup-name {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: $color-text-tertiary;
  letter-spacing: 0.01em;
}

.jb-pgroup--folded .jb-pgroup-name {
  color: $color-text-secondary;
}

.jb-pgroup-sum {
  font-size: 0.72rem;
  color: $color-text-secondary;
  font-family: $typography-font-mono;
  white-space: nowrap;
}

.jb-pgroup-quiet {
  font-size: 0.78rem;
  color: $color-text-secondary;
  margin: 0;
  padding: 8px 0 0;
}
</style>
