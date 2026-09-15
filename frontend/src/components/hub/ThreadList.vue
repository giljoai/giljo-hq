<template>
  <div class="thread-list" data-testid="thread-list">
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
  search: { type: String, default: '' },
  sort: { type: String, default: 'activity' },
})

const scopedThreads = computed(() => {
  if (searchResults.value !== null) return searchResults.value
  if (props.scope === 'project') return commHub.projectThreadList
  if (props.scope === 'town') return commHub.townSquareThreadList
  return commHub.threadList
})

const sortedThreads = computed(() => {
  const rows = [...scopedThreads.value]
  const at = (t) => t.last_message?.created_at || t.last_activity_at || t.created_at || ''
  if (props.sort === 'created') return rows.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
  if (props.sort === 'serial') return rows.sort((a, b) => String(a.chat_id || '').localeCompare(String(b.chat_id || '')))
  return rows.sort((a, b) => String(at(b)).localeCompare(String(at(a))))
})

const displayThreads = computed(() => {
  const rows = sortedThreads.value
  if (searchResults.value === null) return rows
  const serial = aliasSerial(props.search)
  if (serial === null) return rows
  const exact = rows.filter((t) => aliasSerial(t.chat_id) === serial)
  if (!exact.length) return rows
  return [...exact, ...rows.filter((t) => aliasSerial(t.chat_id) !== serial)]
})

function aliasSerial(value) {
  const m = String(value || '').trim().match(/^(?:cht-?)?(\d{1,9})$/i)
  return m ? Number(m[1]) : null
}

const TERMINAL = new Set(['resolved', 'closed'])
function decorate(thread) {
  const terminal = TERMINAL.has(String(thread.status || '').toLowerCase())
  return { ...thread, _yourTurn: !terminal && thread.next_action_owner === userStore.currentUser?.id }
}

function onSelect(threadId) {
  commHub.selectThread(threadId)
  emit('select', threadId)
}

async function onRename({ thread, subject }) {
  try {
    await commHub.renameThread(thread.thread_id, subject)
    showToast({ type: 'success', message: 'Thread renamed.' })
  } catch (err) {
    const msg = err?.response?.data?.detail || err?.message || 'Could not rename this thread.'
    showToast({ type: 'error', message: msg })
  }
}

async function onCopyThreadId(thread) {
  if (!thread?.thread_id) return
  const ok = await copy(thread.thread_id)
  showToast(
    ok
      ? { type: 'success', message: 'Thread id copied — paste it into any harness.' }
      : { type: 'error', message: 'Browser blocked the copy — select and copy manually.' },
  )
}

function onLockInfo() {
  showToast({ type: 'info', message: "Can't delete — kept with the project's 360 memory." })
}

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

const searchResults = ref(null)
let searchDebounce = null

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
