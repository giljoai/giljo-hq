<!--
  HubThreadToolbar.vue — FE-9439

  The row above an open thread: back to the list, search within this thread, and the
  persistent hand toggle that clears "waiting on you".

  EXTRACTED FROM HubView.vue, and not only for tidiness. That file sat at 799 lines
  against an 800-line cap, so it could not absorb a feature at all — the first control
  added to it failed the guardrail. Lifting this row out is the fix at the layer the
  problem lives on: the thread view's chrome is a coherent unit with its own state, and
  HubView goes back to being the thing that chooses between the list and the thread.

  The toggle is the PERSISTENT instance of the pair. The composer's copy is only reachable
  at the bottom of the thread; this one is on screen the whole time one is open, so it
  doubles as the answer to "is anything waiting on me here?" — a status indicator that is
  also the action. It is deliberately smaller, so it sits inside this row's existing
  design height rather than stretching it.

  It calls useMarkHandled() directly rather than taking the state as props: the behaviour
  is shared with the composer through that composable, and threading it down as props
  would put HubView back in the business of owning something it does not use.
-->
<template>
  <div class="hub-thread-toolbar">
    <button type="button" class="hub-thread-toolbar__back" data-testid="hub-back" @click="$emit('back')">
      <v-icon size="16">mdi-arrow-left</v-icon> All threads
    </button>

    <!-- FE-9368 (D): search scoped to THIS thread. The list view's box searches across
         threads on the server; this one filters the timeline already loaded, which is
         why it needs no debounce and no request. -->
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

defineProps({
  // The in-thread filter text. `v-model` from HubView, which owns it because it clears
  // the filter whenever the open thread changes.
  modelValue: { type: String, default: '' },
})

defineEmits(['update:modelValue', 'back'])

const { isYourTurn, clearing, markHandled } = useMarkHandled()
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
  }

  // FE-9368 (D): 560px per operator sizing decision (2026-08-06; 280px read as too small
  // in the live UI). It carries `filter-search` too, which is where the field's border
  // and focus ring come from (the shared mixin keys on that class). The explicit width
  // matters: in this COLUMN layout the mixin's `flex: 1` no longer stretches the field
  // horizontally (flex acts on the column axis), so without it the input collapses to
  // its intrinsic width.
  &__search {
    width: 560px;
    max-width: 560px;
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
