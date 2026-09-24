<template>
  <div v-if="count > 0" class="bulk-bar-wrap" data-testid="bulk-action-bar">
    <div class="bulk-bar smooth-border" role="toolbar" :aria-label="`${count} selected`">
      <span class="bulk-count" data-testid="bulk-count">{{ count }} selected</span>
      <div class="bulk-spacer" />
      <v-btn
        v-if="canArchive"
        variant="text"
        size="small"
        prepend-icon="mdi-archive-arrow-down"
        class="bulk-btn"
        :disabled="busy"
        data-testid="bulk-archive"
        @click="$emit('archive')"
      >Send to archive</v-btn>
      <v-btn
        v-if="canUnarchive"
        variant="text"
        size="small"
        prepend-icon="mdi-archive-arrow-up"
        class="bulk-btn"
        :disabled="busy"
        data-testid="bulk-unarchive"
        @click="$emit('unarchive')"
      >Unarchive</v-btn>
      <v-btn
        v-if="showChain"
        variant="text"
        size="small"
        prepend-icon="mdi-link-variant"
        class="bulk-btn"
        :disabled="busy || !chainReady"
        :title="chainNote || undefined"
        data-testid="bulk-chain"
        @click="$emit('chain')"
      >Chain</v-btn>
      <v-btn
        variant="text"
        size="small"
        prepend-icon="mdi-delete"
        class="bulk-btn bulk-btn--danger"
        :disabled="busy"
        data-testid="bulk-delete"
        @click="confirmDelete = true"
      >Delete</v-btn>
      <v-btn
        variant="text"
        size="small"
        prepend-icon="mdi-checkbox-multiple-blank-outline"
        class="bulk-btn"
        :disabled="busy"
        data-testid="bulk-clear"
        @click="$emit('clear')"
      >Clear</v-btn>
    </div>
    <div v-if="showChain && chainNote" class="bulk-note" data-testid="bulk-chain-note">{{ chainNote }}</div>
    <div v-if="offerAllMatching" class="bulk-note" data-testid="bulk-select-all-offer">
      {{ count }} selected on this page.
      <button type="button" class="bulk-link" data-testid="bulk-select-all-matching" @click="$emit('select-all-matching')">
        <v-icon size="14">mdi-checkbox-multiple-marked-outline</v-icon>
        Select all {{ matchingTotal }} matching
      </button>
    </div>
    <div v-else-if="allMatching" class="bulk-note" data-testid="bulk-all-matching-note">
      All {{ count }} matching rows are selected, including rows on other pages.
    </div>

    <BaseDialog
      v-model="confirmDelete"
      type="danger"
      :title="`Delete ${count} ${countNoun}?`"
      :confirm-label="`Delete ${count}`"
      size="sm"
      @confirm="onConfirmDelete"
      @cancel="confirmDelete = false"
    >
      <p class="mb-3">
        Are you sure you want to delete <strong>{{ count }} {{ countNoun }}</strong>?
      </p>
      <v-alert v-if="deleteNote" type="info" variant="tonal" density="compact">{{ deleteNote }}</v-alert>
    </BaseDialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import BaseDialog from '@/components/common/BaseDialog.vue'

const props = defineProps({
  count: { type: Number, default: 0 },
  pageCount: { type: Number, default: 0 },
  matchingTotal: { type: Number, default: 0 },
  allMatching: { type: Boolean, default: false },
  canArchive: { type: Boolean, default: false },
  canUnarchive: { type: Boolean, default: false },
  showChain: { type: Boolean, default: false },
  chainReady: { type: Boolean, default: false },
  chainNote: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  noun: { type: Array, default: () => ['item', 'items'] },
  deleteNote: { type: String, default: '' },
})

const emit = defineEmits(['archive', 'unarchive', 'chain', 'delete', 'clear', 'select-all-matching'])

const confirmDelete = ref(false)
const countNoun = computed(() => (props.count === 1 ? props.noun[0] : props.noun[1]))

function onConfirmDelete() {
  confirmDelete.value = false
  emit('delete')
}

const offerAllMatching = computed(
  () => !props.allMatching && props.pageCount > 0 && props.count >= props.pageCount && props.matchingTotal > props.count,
)
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;

.bulk-bar-wrap {
  margin-bottom: 16px;
}

.bulk-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
  padding: 6px 12px;
  border-radius: $border-radius-rounded;
  background: rgba($color-brand-yellow, 0.08);
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.3);
}

.bulk-count {
  font-size: 0.82rem;
  font-weight: 600;
  color: $color-text-primary;
  white-space: nowrap;
}

.bulk-spacer {
  flex: 1;
}

.bulk-btn {
  text-transform: none;
  letter-spacing: 0;
  color: $color-text-primary;
}

.bulk-btn--danger {
  color: $color-status-error;
}

.bulk-note {
  margin-top: 6px;
  padding: 0 12px;
  font-size: 0.74rem;
  color: $color-text-secondary;
}

.bulk-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 4px;
  padding: 0;
  border: none;
  background: none;
  font: inherit;
  font-weight: 600;
  color: $color-brand-yellow;
  cursor: pointer;
}

.bulk-link:focus-visible {
  outline: 2px solid $color-brand-yellow;
  outline-offset: 2px;
}
</style>
