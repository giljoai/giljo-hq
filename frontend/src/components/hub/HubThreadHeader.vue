<template>
    <div class="hub-thread-header__head" data-testid="thread-header">
      <div class="hub-thread-header__title-row">
        <template v-if="renamingHeader">
          <input
            ref="headerRenameInput"
            v-model="headerDraft"
            class="hub-thread-header__rename smooth-border"
            data-testid="thread-header-rename-input"
            @keydown.enter="saveHeaderRename"
            @keydown.esc="renamingHeader = false"
            @blur="renamingHeader = false"
          />
          <span class="hub-thread-header__rename-hint">↵ save · esc cancel</span>
        </template>

        <template v-else>
          <span class="hub-thread-header__serial" data-testid="thread-header-serial">
            {{ commHub.selectedThread?.chat_id }}
          </span>
          <h2 class="hub-thread-header__title" data-testid="thread-header-title">
            {{ headerTitle }}
          </h2>
          <button
            type="button"
            class="hub-thread-header__action"
            :title="headerLocked ? 'Project logs are named after their project' : 'Rename'"
            :aria-label="headerLocked ? 'Locked — named after its project' : 'Rename thread'"
            data-testid="thread-header-rename"
            @click="startHeaderRename"
          >
            <v-icon size="16">{{ headerLocked ? 'mdi-lock-outline' : 'mdi-pencil-outline' }}</v-icon>
          </button>
          <button
            type="button"
            class="hub-thread-header__action"
            title="Copy thread id"
            aria-label="Copy thread id"
            data-testid="thread-header-copy"
            @click="copyThreadId"
          >
            <v-icon size="16">mdi-content-copy</v-icon>
          </button>
        </template>
      </div>

      <ThreadDates
        v-if="commHub.selectedThread"
        :thread="commHub.selectedThread"
        size="md"
        data-testid="thread-header-dates"
      />

      <div class="hub-thread-header__meta">
        <div v-if="headerAgents.length" class="hub-thread-header__pills" data-testid="thread-header-pills">
          <AgentPill v-for="a in headerAgents" :key="a.participant_id" :participant="a" />
        </div>
        <ThreadRetagMenu
          v-if="commHub.selectedThreadId"
          :product-id="commHub.selectedThread?.product_id"
          :products="productStore.products"
          @retag="onRetagProduct"
        />
        <div class="hub-thread-header__scope" data-testid="thread-header-scope">
          <v-icon v-if="headerLocked" size="13" class="mr-1">mdi-eye-off-outline</v-icon>
          {{ headerScopeNote }}
        </div>
      </div>

      <button
        type="button"
        class="hub-thread-header__id"
        title="Copy thread id"
        data-testid="thread-header-id"
        @click="copyThreadId"
      >
        <span class="hub-thread-header__id-cmd">join_thread</span>
        <span class="hub-thread-header__id-val">{{ commHub.selectedThreadId }}</span>
        <v-icon size="13">mdi-content-copy</v-icon>
      </button>
    </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useProductStore } from '@/stores/products'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { parseErrorResponse } from '@/utils/errorMessages'
import AgentPill from '@/components/hub/AgentPill.vue'
import ThreadRetagMenu from '@/components/hub/ThreadRetagMenu.vue'
import ThreadDates from '@/components/hub/ThreadDates.vue'

const commHub = useCommHubStore()
const productStore = useProductStore()
const { showToast } = useToast()
const { copy } = useClipboard()

const headerAgents = computed(() =>
  commHub.participantsFor(commHub.selectedThreadId || '').filter((p) => p.participant_type !== 'user'),
)

const headerLocked = computed(() => commHub.selectedThread?.project_id != null)
const headerTitle = computed(() => {
  const t = commHub.selectedThread?.title || commHub.selectedThread?.subject
  return t || 'Untitled thread'
})
const headerScopeNote = computed(() =>
  headerLocked.value
    ? "Kept with the project record — not part of an agent's working context."
    : 'Visible to the agents registered here, on their next poll',
)

const renamingHeader = ref(false)
const headerDraft = ref('')
const headerRenameInput = ref(null)

async function startHeaderRename() {
  if (headerLocked.value) {
    showToast({ type: 'info', message: 'Project logs are named after their project.' })
    return
  }
  headerDraft.value = commHub.selectedThread?.subject || ''
  renamingHeader.value = true
  await nextTick()
  headerRenameInput.value?.focus()
  headerRenameInput.value?.select()
}

async function saveHeaderRename() {
  const next = headerDraft.value.trim()
  const current = commHub.selectedThread?.subject
  renamingHeader.value = false
  if (!next || next === current) return
  try {
    await commHub.renameThread(commHub.selectedThreadId, next)
    showToast({ type: 'success', message: 'Thread renamed.' })
  } catch (err) {
    const msg = parseErrorResponse(err).message || 'Could not rename this thread.'
    showToast({ type: 'error', message: msg })
  }
}

async function onRetagProduct(productId) {
  const threadId = commHub.selectedThreadId
  if (!threadId) return
  try {
    await commHub.retagThread(threadId, { productId })
    showToast({ type: 'success', message: productId ? 'Product updated.' : 'Product cleared.' })
  } catch (err) {
    const msg = parseErrorResponse(err).message || 'Could not retag this thread.'
    showToast({ type: 'error', message: msg })
  }
}

async function copyThreadId() {
  const ok = await copy(commHub.selectedThreadId)
  showToast(
    ok
      ? { type: 'success', message: 'Thread id copied — paste it into any harness.' }
      : { type: 'error', message: 'Browser blocked the copy — select and copy manually.' },
  )
}

</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

.hub-thread-header {
  &__meta {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    min-width: 0;
  }

  &__serial {
    flex: none;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.1875rem; // 19 — the header's louder cousin of the card's 15
    font-weight: 700;
    color: $color-brand-yellow;
    letter-spacing: 0.01em;
    margin-right: v.$spacing-sm;
  }

  &__pills {
    display: flex;
    flex-wrap: wrap;
    gap: v.$spacing-xs;
    margin: v.$spacing-xs 0;
  }

  &__head {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: v.$spacing-sm v.$spacing-md v.$spacing-md;
  }

  &__title-row {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    min-height: 28px;
  }

  &__title {
    font-family: 'Outfit', sans-serif;
    font-size: 1.0625rem; // 17
    font-weight: 600;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  &__action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    flex-shrink: 0;
    border: none;
    background: transparent;
    color: var(--text-muted);
    border-radius: $border-radius-default; // 8
    cursor: pointer;
    transition: color $transition-fast, background $transition-fast;

    &:hover {
      color: var(--text-primary);
      background: rgba(255, 255, 255, 0.08);
    }
  }

  &__rename {
    flex: 1;
    min-width: 0;
    font-family: 'Outfit', sans-serif;
    font-size: 1.0625rem;
    font-weight: 600;
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.05);
    border: none;
    border-radius: $border-radius-md; // 12 — inputs
    padding: 4px 10px;

    &:focus { outline: none; }
  }

  &__scope {
    display: flex;
    align-items: center;
    margin-left: auto; // right-aligned on the pill row, per the prototype
    flex: none;
    font-size: 0.71875rem; // 11.5
    color: var(--text-muted);
  }

  &__rename-hint,
  &__id-cmd { color: var(--text-muted); }
  &__id-val { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  &__id {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border: none;
    cursor: pointer;
    min-width: 0;
    .v-icon { color: $color-brand-yellow; flex: none; }

    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem; // 11 — the floor
    color: var(--text-muted);
    white-space: nowrap;
  }

  &__id {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border: none;
    cursor: pointer;
    min-width: 0;
    .v-icon { color: $color-brand-yellow; flex: none; }

    align-self: flex-start;
    padding: 3px 8px;
    border-radius: $border-radius-default; // 8
    background: rgba(0, 0, 0, 0.28);
    overflow-x: auto;
    max-width: 100%;
  }

  &__id-cmd { color: var(--text-muted); }
  &__id-val { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
</style>
