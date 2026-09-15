<template>
  <div class="hub-thread-toolbar">
    <button type="button" class="hub-thread-toolbar__back" data-testid="hub-back" @click="$emit('back')">
      <v-icon size="16">mdi-arrow-left</v-icon> All threads
    </button>

    <div class="hub-thread-toolbar__row">
      <v-text-field
        :model-value="modelValue"
        class="filter-search hub-thread-toolbar__search"
        prepend-inner-icon="mdi-magnify"
        placeholder="Search this thread..."
        aria-label="Search messages in this thread"
        variant="solo"
        density="compact"
        flat
        hide-details
        clearable
        data-testid="thread-message-search"
        @update:model-value="$emit('update:modelValue', $event)"
      />
      <div
        class="hub-thread-toolbar__order"
        role="group"
        aria-label="Message order"
        data-testid="message-order"
      >
        <button
          type="button"
          class="hub-thread-toolbar__order-btn"
          :class="{ 'hub-thread-toolbar__order-btn--active': !newestFirst }"
          :aria-pressed="!newestFirst ? 'true' : 'false'"
          title="Oldest on top"
          data-testid="message-order-oldest"
          @click="setOrder(OLDEST_FIRST)"
        >
          <v-icon size="15">mdi-sort-clock-ascending-outline</v-icon>
          <span class="hub-thread-toolbar__order-label">Oldest on top</span>
        </button>
        <button
          type="button"
          class="hub-thread-toolbar__order-btn"
          :class="{ 'hub-thread-toolbar__order-btn--active': newestFirst }"
          :aria-pressed="newestFirst ? 'true' : 'false'"
          title="Newest on top"
          data-testid="message-order-newest"
          @click="setOrder(NEWEST_FIRST)"
        >
          <v-icon size="15">mdi-sort-clock-descending-outline</v-icon>
          <span class="hub-thread-toolbar__order-label">Newest on top</span>
        </button>
      </div>
      <MarkHandledToggle
        :active="isYourTurn"
        :disabled="clearing"
        size="sm"
        data-testid="search-mark-handled"
        @click="markHandled"
      />
    </div>
  </div>
</template>

<script setup>
import MarkHandledToggle from '@/components/hub/MarkHandledToggle.vue'
import { useMarkHandled } from '@/components/hub/useMarkHandled'
import { useHubMessageOrder, OLDEST_FIRST, NEWEST_FIRST } from '@/components/hub/useHubMessageOrder'

defineProps({
  modelValue: { type: String, default: '' },
})

defineEmits(['update:modelValue', 'back'])

const { isYourTurn, clearing, markHandled } = useMarkHandled()
const { newestFirst, setOrder } = useHubMessageOrder()
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

@use '../../styles/list-filter-bar' as filterBar;

.hub-thread-toolbar {
  // FE-9368 follow-up: back link then the search row, stacked and left-aligned so the
  // search sits in the same column as the title cluster below it rather than floating
  // detached in the top-right corner.
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: v.$spacing-sm;
  margin-bottom: v.$spacing-sm;

  @include filterBar.list-filter-bar;

  // FE-9439: the search field and the hand toggle share a row. The back link stays on
  // its own line above — the toggle belongs beside the thing it sits at eye level with,
  // not beside "All threads".
  &__row {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    // FE-9593: the row gained the order control. On a narrow viewport the search keeps
    // its width and the controls wrap under it rather than anything clipping.
    flex-wrap: wrap;
    max-width: 100%;
  }

  // FE-9593: two-position segmented control, sized to its own labels. Same chrome as
  // the filter fields (inset 1px border, default radius) so it reads as one toolbar.
  &__order {
    display: inline-flex;
    flex: none;
    padding: 3px;
    gap: 2px;
    border-radius: $border-radius-default; // 8
    background: $elevation-raised;
    box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255, 255, 255, 0.10));
  }

  &__order-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 30px;
    padding: 0 10px;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: var(--text-muted, #{$color-text-secondary});
    font-size: 0.75rem; // 12
    font-weight: 600;
    white-space: nowrap;
    cursor: pointer;
    transition: color $transition-fast, background $transition-fast;

    &:hover { color: $color-text-primary; }

    &--active {
      color: $color-brand-yellow;
      background: rgba($color-brand-yellow, 0.12);
    }
  }

  // Tablet band and below: icons carry the control; the labels stay in the titles.
  @media (max-width: $breakpoint-tablet) {
    &__order-label { display: none; }
  }

  // FE-9368 (D): 560px per operator sizing decision (2026-08-06; 280px read as too small
  // in the live UI). It carries `filter-search` too, which is where the field's border
  // and focus ring come from (the shared mixin keys on that class). The explicit width
  // matters: in this COLUMN layout the mixin's `flex: 1` no longer stretches the field
  // horizontally (flex acts on the column axis), so without it the input collapses to
  // its intrinsic width.
  &__search {
    width: 560px;
    // FE-9593: `min()` so the field never exceeds its row on a tablet-band viewport.
    max-width: min(560px, 100%);
  }

  &__back {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font-size: 0.8125rem; // 13
    color: var(--text-muted);
    transition: color $transition-fast;

    &:hover { color: $color-brand-yellow; }
  }
}
</style>
