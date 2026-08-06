<template>
  <div class="thread-list" data-testid="thread-list">
    <!-- FE-9365c: the search box moved UP into HubView's shared filter bar, so the
         Hub has the same search | sort | primary | outlined row as Products and
         Projects. The query arrives as a prop; the debounce and the server search
         stay here, where the list already owns its own data. -->
    <div class="thread-list__rows" data-testid="thread-rows">
      <div v-if="commHub.loading" class="thread-list__empty">
        <v-progress-circular indeterminate size="20" />
      </div>

      <div
        v-else-if="displayThreads.length === 0"
        class="thread-list__empty"
        data-testid="thread-list-empty"
      >
        No threads found.
      </div>

      <ThreadCard
        v-for="thread in displayThreads"
        :key="thread.thread_id"
        :thread="decorate(thread)"
        :selected="commHub.selectedThreadId === thread.thread_id"
        @open="onSelect"
        @rename="onRename"
        @copy="onCopyThreadId"
        @delete="onRequestDelete"
        @lock-info="onLockInfo"
      />
    </div>

    <!-- Soft-delete confirmation — states the real consequence. -->
    <BaseDialog
      v-model="showDeleteDialog"
      type="danger"
      title="Delete this thread?"
      confirm-label="Delete"
      size="sm"
      :loading="deleting"
      data-testid="thread-delete-dialog"
      @confirm="onConfirmDelete"
      @cancel="showDeleteDialog = false"
    >
      <p class="mb-3">
        Delete
        <strong>{{ threadToDelete?.chat_id || '' }}</strong>
        <span v-if="threadToDelete?.subject">— "{{ threadToDelete.subject }}"</span>?
      </p>
      <v-alert type="info" variant="tonal" density="compact">
        It disappears from the Hub. The message history stays in the database but is no
        longer shown, and agents holding the id can't post to it.
      </v-alert>
    </BaseDialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'
import { useClipboard } from '@/composables/useClipboard'
import { useToast } from '@/composables/useToast'
import BaseDialog from '@/components/common/BaseDialog.vue'
import ThreadCard from '@/components/hub/ThreadCard.vue'

const commHub = useCommHubStore()
const userStore = useUserStore()
const { copy } = useClipboard()
const { showToast } = useToast()

const emit = defineEmits(['select'])

const props = defineProps({
  scope: {
    type: String,
    default: 'all',
    validator: (v) => ['all', 'project', 'town'].includes(v),
  },
  // FE-9365c: both now come from HubView's shared filter bar.
  search: { type: String, default: '' },
  sort: { type: String, default: 'activity' },
})

// ---- display list ----
const scopedThreads = computed(() => {
  if (searchResults.value !== null) return searchResults.value
  if (props.scope === 'project') return commHub.projectThreadList
  if (props.scope === 'town') return commHub.townSquareThreadList
  return commHub.threadList
})

// Sorted from the filter bar's select. Copied before sorting — `sort()` mutates in
// place, and these arrays are store getters, so sorting them directly would reorder
// the store's own state and leak this view's preference into every other consumer.
const displayThreads = computed(() => {
  const rows = [...scopedThreads.value]
  const at = (t) => t.last_message?.created_at || t.last_activity_at || t.created_at || ''
  if (props.sort === 'created') return rows.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
  if (props.sort === 'serial') return rows.sort((a, b) => String(a.chat_id || '').localeCompare(String(b.chat_id || '')))
  return rows.sort((a, b) => String(at(b)).localeCompare(String(at(a))))
})

// The card renders one thread and knows nothing of the viewer; the "waiting on you"
// state is list-level (it depends on the current user), so it is decorated on here.
//
// FE-9365i: a TERMINAL thread is never "waiting on you", whoever the baton was parked
// on when it ended. Operator caught it live (2026-08-05): resolved threads wore the
// gold frame and raised hand because the baton simply stopped where the conversation
// stopped — "done" and "waiting on you" cannot both be true. The attention strip
// already applied this filter; the cards now share it.
const TERMINAL = new Set(['resolved', 'closed'])
function decorate(thread) {
  const terminal = TERMINAL.has(String(thread.status || '').toLowerCase())
  return { ...thread, _yourTurn: !terminal && thread.next_action_owner === userStore.currentUser?.id }
}

// ---- selection ----
function onSelect(threadId) {
  commHub.selectThread(threadId)
  emit('select', threadId)
}

// ---- rename (via the BE-9289b PATCH) ----
async function onRename({ thread, subject }) {
  try {
    await commHub.renameThread(thread.thread_id, subject)
    showToast({ type: 'success', message: 'Thread renamed.' })
  } catch (err) {
    const msg = err?.response?.data?.detail || err?.message || 'Could not rename this thread.'
    showToast({ type: 'error', message: msg })
  }
}

// ---- copy the thread id (the UUID an agent needs, not the CHT alias) ----
async function onCopyThreadId(thread) {
  if (!thread?.thread_id) return
  const ok = await copy(thread.thread_id)
  showToast(
    ok
      ? { type: 'success', message: 'Thread id copied — paste it into any harness.' }
      : { type: 'error', message: 'Browser blocked the copy — select and copy manually.' },
  )
}

// ---- the project-thread lock explains itself instead of being a missing button ----
function onLockInfo() {
  showToast({ type: 'info', message: "Can't delete — kept with the project's 360 memory." })
}

// ---- soft delete ----
const showDeleteDialog = ref(false)
const threadToDelete = ref(null)
const deleting = ref(false)

function onRequestDelete(thread) {
  threadToDelete.value = thread
  showDeleteDialog.value = true
}

async function onConfirmDelete() {
  const thread = threadToDelete.value
  if (!thread?.thread_id) return
  deleting.value = true
  try {
    await commHub.deleteThread(thread.thread_id)
    showToast({ type: 'success', message: 'Thread deleted.' })
    showDeleteDialog.value = false
    threadToDelete.value = null
  } catch (err) {
    const msg = err?.response?.data?.detail || err?.message || 'Failed to delete thread.'
    showToast({ type: 'error', message: msg })
  } finally {
    deleting.value = false
  }
}

// ---- search (spans every scope) ----
const searchResults = ref(null)
let searchDebounce = null

// Driven by the prop from HubView's filter bar. Debounced here rather than there so
// the list keeps owning when it talks to the server — the bar only reports keystrokes.
watch(
  () => props.search,
  (val) => {
    clearTimeout(searchDebounce)
    if (!val || val.trim() === '') {
      searchResults.value = null
      return
    }
    searchDebounce = setTimeout(async () => {
      searchResults.value = await commHub.searchThreads(val.trim())
    }, 350)
  },
)

onBeforeUnmount(() => clearTimeout(searchDebounce))
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

.thread-list {
  display: flex;
  flex-direction: column;

  // FE-9365c: ONE full-width card per row at every width. No grid, no side-by-side.
  // Top-aligned — a short list leaves empty dot-grid below rather than stretching the
  // cards to fill, which would make three threads look like a full board.
  &__rows {
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-width: 1120px;
    align-content: flex-start;
  }

  &__empty {
    padding: v.$spacing-lg v.$spacing-md;
    text-align: center;
    color: var(--text-muted);
    font-size: 0.8125rem; // 13
  }
}
</style>
