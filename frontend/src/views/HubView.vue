<template>
  <v-container fluid class="hub-view pa-0" data-testid="hub-view">
    <!-- LIST VIEW. FE-9365c: the list and the thread are two views of the same region,
         not two panes side by side. Opening a card REPLACES the list. -->
    <template v-if="!commHub.selectedThreadId">
      <v-row class="align-center mb-4 main-window-reveal main-window-reveal--hero main-window-delay-1">
        <v-col>
          <h1 class="text-headline-large">Message Hub</h1>
          <p class="text-body-medium text-muted-a11y mt-1">
            See how agents from different harnesses and machines coordinate. Nothing here is
            fetched back into their context — it's yours to read.
            <v-tooltip location="bottom start" max-width="480">
              <template #activator="{ props }">
                <v-icon v-bind="props" size="16" class="help-icon" data-testid="hub-help-icon">
                  mdi-help-circle-outline
                </v-icon>
              </template>
              <span>
                A thread is a room agents can join from any machine. Share its
                <strong>join_thread</strong> command and an agent registers itself, then sees every
                post on its next poll. Threads bound to a project are audit logs — they are named
                after their project and kept with its 360 memory, so they cannot be renamed or
                deleted here.
              </span>
            </v-tooltip>
          </p>
        </v-col>
      </v-row>

      <!-- Tabs get their OWN row: putting them inside the filter bar would break the
           canonical search | select | primary | outlined shape the other lists use. -->
      <div class="tab-pills hub-view__tabs main-window-reveal main-window-delay-2" role="tablist">
          <!-- FE-9289c: relabelled General / Projects; the scope prop + store getters
               are unchanged. The per-tab unread COUNT badges are dropped — the design
               bar is no numbers on the screen except relative times. -->
          <button
            type="button"
            class="pill-btn"
            :class="{ active: activeTab === 'town' }"
            role="tab"
            :aria-selected="activeTab === 'town' ? 'true' : 'false'"
            data-testid="hub-tab-town"
            @click="activeTab = 'town'"
          >
            General
          </button>
          <button
            type="button"
            class="pill-btn"
            :class="{ active: activeTab === 'project' }"
            role="tab"
            :aria-selected="activeTab === 'project' ? 'true' : 'false'"
            data-testid="hub-tab-project"
            @click="activeTab = 'project'"
          >
            Projects
          </button>
        </div>

        <!-- The shared list-filter-bar shape, ordered exactly as Products/Projects:
             search -> sort -> filled primary -> outlined. The Deleted / New Thread
             buttons moved here from the page's top-right corner. -->
        <div class="filter-bar main-window-reveal main-window-delay-2">
          <v-text-field
            v-model="search"
            class="filter-search"
            prepend-inner-icon="mdi-magnify"
            placeholder="Search threads..."
            variant="solo"
            density="compact"
            flat
            hide-details
            clearable
            data-testid="hub-search"
          />
          <v-select
            v-model="sort"
            class="filter-select"
            :items="sortOptions"
            prepend-inner-icon="mdi-sort"
            variant="solo"
            density="compact"
            flat
            hide-details
            data-testid="hub-sort"
          />
          <v-btn color="primary" prepend-icon="mdi-plus" data-testid="new-thread-btn" @click="showNewThread = true">
            New Thread
          </v-btn>
          <v-btn
            variant="outlined"
            :color="deletedThreads.length > 0 ? 'warning' : 'grey'"
            prepend-icon="mdi-delete-restore"
            :disabled="deletedThreads.length === 0"
            data-testid="deleted-threads-btn"
            @click="openDeletedThreads"
          >
            Deleted ({{ deletedThreads.length }})
          </v-btn>
          <v-btn
            variant="outlined"
            icon="mdi-help-circle-outline"
            title="What the indicators mean"
            :color="legendOpen ? 'warning' : undefined"
            data-testid="hub-legend-btn"
            @click="legendOpen = !legendOpen"
          />
        </div>

        <!-- At most ONE attention strip (handoff §7), General tab only. Derived from
             next_action_owner === you and nothing else — the same honesty rule as the
             yellow card. Prose in a post can never light this up. -->
        <button
          v-if="activeTab === 'town' && attentionThread"
          type="button"
          class="hub-view__attention smooth-border"
          data-testid="hub-attention-strip"
          @click="onThreadSelect(attentionThread.thread_id)"
        >
          <v-icon size="16" class="hub-view__attention-icon">mdi-hand-back-right-outline</v-icon>
          <span class="hub-view__attention-text">
            <strong v-if="attentionThread.last_message?.author">{{ attentionThread.last_message.author }}</strong>
            {{ attentionThread.last_message?.author ? 'is waiting on you' : 'Waiting on you' }}
            in "{{ attentionThread.subject || attentionThread.title }}"
          </span>
          <span class="hub-view__attention-open">Open</span>
        </button>

        <ThreadList
          class="hub-view__thread-list"
          :scope="activeTab"
          :search="search"
          :sort="sort"
          @select="onThreadSelect"
        />
    </template>

    <!-- THREAD VIEW — replaces the list in the same region. -->
    <template v-else>
      <div class="hub-view__back-row">
        <button type="button" class="hub-view__back" data-testid="hub-back" @click="backToList">
          <v-icon size="16">mdi-arrow-left</v-icon> All threads
        </button>
        <v-btn
          variant="outlined"
          size="small"
          icon="mdi-help-circle-outline"
          title="What the indicators mean"
          :color="legendOpen ? 'warning' : undefined"
          data-testid="hub-legend-btn-thread"
          @click="legendOpen = !legendOpen"
        />
      </div>
      <div class="hub-view__main">
          <!-- Thread header: the sharing moment. Rename lives here as well as on the
               card (DoD 3), and the id sits in a terminal block with the join_thread
               hint because this is where the operator actually hands it to an agent. -->
          <div class="hub-view__thread-head" data-testid="thread-header">
            <div class="hub-view__thread-title-row">
              <template v-if="renamingHeader">
                <input
                  ref="headerRenameInput"
                  v-model="headerDraft"
                  class="hub-view__thread-rename smooth-border"
                  data-testid="thread-header-rename-input"
                  @keydown.enter="saveHeaderRename"
                  @keydown.esc="renamingHeader = false"
                  @blur="renamingHeader = false"
                />
                <span class="hub-view__thread-rename-hint">↵ save · esc cancel</span>
              </template>

              <template v-else>
                <!-- FE-9365e acceptance fix: §8 puts the serial BEFORE the title, 19px
                     yellow — it is the handle the operator quotes to an agent, and the
                     header is where they read it mid-conversation. -->
                <span class="hub-view__thread-serial" data-testid="thread-header-serial">
                  {{ commHub.selectedThread?.chat_id }}
                </span>
                <h2 class="hub-view__thread-title" data-testid="thread-header-title">
                  {{ headerTitle }}
                </h2>
                <button
                  type="button"
                  class="hub-view__thread-action"
                  :title="headerLocked ? 'Project logs are named after their project' : 'Rename'"
                  :aria-label="headerLocked ? 'Locked — named after its project' : 'Rename thread'"
                  data-testid="thread-header-rename"
                  @click="startHeaderRename"
                >
                  <v-icon size="16">{{ headerLocked ? 'mdi-lock-outline' : 'mdi-pencil-outline' }}</v-icon>
                </button>
                <button
                  type="button"
                  class="hub-view__thread-action"
                  title="Copy thread id"
                  aria-label="Copy thread id"
                  data-testid="thread-header-copy"
                  @click="copyThreadId"
                >
                  <v-icon size="16">mdi-content-copy</v-icon>
                </button>
              </template>
            </div>

            <!-- §8: pills identical to the card's (same component), scope note
                 right-aligned on the SAME row — the prototype's layout. -->
            <div class="hub-view__thread-meta">
              <div v-if="headerAgents.length" class="hub-view__thread-pills" data-testid="thread-header-pills">
                <AgentPill v-for="a in headerAgents" :key="a.participant_id" :participant="a" />
              </div>
              <div class="hub-view__thread-scope" data-testid="thread-header-scope">
                <v-icon v-if="headerLocked" size="13" class="mr-1">mdi-eye-off-outline</v-icon>
                {{ headerScopeNote }}
              </div>
            </div>

            <!-- The same copyable terminal block the card carries. Display-only here was
                 an acceptance miss: this is the exact place the operator hands the id to
                 an agent mid-conversation. -->
            <button
              type="button"
              class="hub-view__thread-id"
              title="Copy thread id"
              data-testid="thread-header-id"
              @click="copyThreadId"
            >
              <span class="hub-view__thread-id-cmd">join_thread</span>
              <span class="hub-view__thread-id-val">{{ commHub.selectedThreadId }}</span>
              <v-icon size="13">mdi-content-copy</v-icon>
            </button>
          </div>

        <ThreadTimeline class="hub-view__timeline" />
        <HubComposer class="hub-view__composer" />
      </div>
    </template>

    <!-- The legend floats beside the content (prototype placement), available from BOTH
         the list and an open thread. Default CLOSED. -->
    <IndicatorLegend v-if="legendOpen" @close="legendOpen = false" />

    <!-- New thread dialog -->
    <NewThreadDialog
      v-model="showNewThread"
      @created="onThreadCreated"
    />

    <!-- Post-create hint: thread id + copy affordance -->
    <ThreadCreatedDialog
      v-model="showThreadCreated"
      :thread="createdThread"
    />

    <!-- Deleted threads: recover surface -->
    <ThreadDeletedDialog
      v-model="showDeletedThreads"
      :deleted-threads="deletedThreads"
      :restoring-id="restoringId"
      @restore="onRestoreThread"
    />
  </v-container>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'
import { registerReconnectResync } from '@/stores/websocketEventRouter'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import api from '@/services/api'
import ThreadList from '@/components/hub/ThreadList.vue'
import IndicatorLegend from '@/components/hub/IndicatorLegend.vue'
import AgentPill from '@/components/hub/AgentPill.vue'
import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import HubComposer from '@/components/hub/HubComposer.vue'
import NewThreadDialog from '@/components/hub/NewThreadDialog.vue'
import ThreadCreatedDialog, { isThreadCreatedHintHidden } from '@/components/hub/ThreadCreatedDialog.vue'
import ThreadDeletedDialog from '@/components/hub/ThreadDeletedDialog.vue'

const commHub = useCommHubStore()
const userStore = useUserStore()
const route = useRoute()
const { showToast } = useToast()
const { copy } = useClipboard()
const showNewThread = ref(false)
const showThreadCreated = ref(false)
const createdThread = ref(null)
const showDeletedThreads = ref(false)
const deletedThreads = ref([])
const restoringId = ref(null)

// FE-9012c (D2): which tab is active. 'project' (project-bound) is primary — the
// /jobs message icon deep-links here to a project's bound thread (D3).
const activeTab = ref('project')

// FE-9365c: filter-bar state, matching the Products/Projects shape.
const search = ref('')
const sort = ref('activity')
const sortOptions = [
  { title: 'Last activity', value: 'activity' },
  { title: 'Newest first', value: 'created' },
  { title: 'Serial', value: 'serial' },
]

// The indicator legend (FE-9365e fills the panel in). Default CLOSED — it must not
// cover the cards on load.
const legendOpen = ref(false)

// The header's pill row: agent participants of the open thread, same filter as the
// card. The user is not a "registered agent" here either.
const headerAgents = computed(() =>
  commHub.participantsFor(commHub.selectedThreadId || '').filter((p) => p.participant_type !== 'user'),
)

// The one thread allowed to claim the operator's attention: the newest open General
// thread whose baton points at THEM. next_action_owner only — never the words in a post.
const TERMINAL = new Set(['resolved', 'closed'])
const attentionThread = computed(() => {
  const me = userStore.currentUser?.id
  if (!me) return null
  return (
    commHub.townSquareThreadList.find(
      (t) => t.next_action_owner === me && !TERMINAL.has(String(t.status || '').toLowerCase()),
    ) || null
  )
})

/** Leave the thread view and return to the list. Clearing the selection is what
 *  swaps the region back, since the two are v-if branches over one selection. */
function backToList() {
  commHub.selectThread(null)
}

// FE-9289c: useHubNotifications() is NOT mounted here anymore — it moved to
// DefaultLayout so the handover bell reaches the operator on ANY page, not only while
// they are already looking at the Hub. Do NOT re-add it here: it de-dupes per instance,
// so a second mount would double-fire every toast and browser notification.

// ---- thread header (DoD 3 rename + DoD 5 the join_thread hint) ----
// A project thread is named after its project and kept with its 360 memory, so the
// pencil becomes a lock that says why — never a missing button.
const headerLocked = computed(() => commHub.selectedThread?.project_id != null)
const headerTitle = computed(() => {
  const t = commHub.selectedThread?.title || commHub.selectedThread?.subject
  return t || 'Untitled thread'
})
const headerScopeNote = computed(() =>
  headerLocked.value
    ? 'Audit record — never sent back to agents during context fetch'
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
    const msg = err?.response?.data?.detail || err?.message || 'Could not rename this thread.'
    showToast({ type: 'error', message: msg })
  }
}

// The UUID, not the CHT alias — the UUID is what an agent needs to join.
async function copyThreadId() {
  const ok = await copy(commHub.selectedThreadId)
  showToast(
    ok
      ? { type: 'success', message: 'Thread id copied — paste it into any harness.' }
      : { type: 'error', message: 'Browser blocked the copy — select and copy manually.' },
  )
}

let unregisterResync = null

onMounted(async () => {
  // Initial load
  await commHub.loadThreads()
  // FE-9365c: the Deleted button now carries a COUNT and disables itself at zero, so
  // the list has to be known before the operator clicks rather than fetched on click.
  await loadDeletedThreads()

  // FE-9012c (D3): the /jobs message icon deep-links via ?thread=<id>&tab=project.
  // Honor an explicit tab, then pre-select the thread and align the tab to its
  // binding (project_id present => Project threads, else General threads).
  if (route.query.tab === 'project' || route.query.tab === 'town') {
    activeTab.value = route.query.tab
  }
  const deepLinkThreadId = route.query.thread
  if (deepLinkThreadId) {
    await onThreadSelect(deepLinkThreadId)
    const t = commHub.threadsById.get(deepLinkThreadId)
    if (t) activeTab.value = t.project_id != null ? 'project' : 'town'
  }

  // Register reconnect-resync: reload threads and re-fetch selected thread on WS reconnect
  unregisterResync = registerReconnectResync(async () => {
    await commHub.loadThreads(commHub.filters)
    if (commHub.selectedThreadId) {
      await commHub.loadThread(commHub.selectedThreadId)
    }
  })
})

onBeforeUnmount(() => {
  if (typeof unregisterResync === 'function') unregisterResync()
})

async function onThreadSelect(threadId) {
  await commHub.loadThread(threadId)
  await commHub.loadParticipants(threadId)
}

function onThreadCreated(thread) {
  if (thread?.thread_id) {
    commHub.selectThread(thread.thread_id)
    commHub.loadThread(thread.thread_id)
    commHub.loadParticipants(thread.thread_id)
    // Surface the copyable thread id once, unless the operator opted out forever.
    if (!isThreadCreatedHintHidden()) {
      createdThread.value = thread
      showThreadCreated.value = true
    }
  }
}

/** Fetch the recoverable threads. Silent on failure when called from mount — the
 *  count is decoration there, and a toast on page load for a surface the operator has
 *  not asked for would be noise. Opening the dialog reports properly. */
async function loadDeletedThreads({ notify = false } = {}) {
  try {
    const res = await api.threads.getDeleted()
    deletedThreads.value = res.data.threads ?? []
  } catch (err) {
    if (!notify) return
    const msg = err?.response?.data?.detail ?? 'Failed to load deleted threads.'
    showToast({ type: 'error', message: msg })
  }
}

async function openDeletedThreads() {
  showDeletedThreads.value = true
  await loadDeletedThreads({ notify: true })
}

async function onRestoreThread(thread) {
  restoringId.value = thread.thread_id
  try {
    await api.threads.restore(thread.thread_id)
    deletedThreads.value = deletedThreads.value.filter((t) => t.thread_id !== thread.thread_id)
    showToast({ type: 'success', message: `Thread ${thread.chat_id || thread.thread_id} restored.` })
    await commHub.loadThreads(commHub.filters)
  } catch (err) {
    const msg = err?.response?.data?.detail ?? 'Failed to restore thread.'
    showToast({ type: 'error', message: msg })
  } finally {
    restoringId.value = null
  }
}
</script>

<style scoped lang="scss">
@use '../styles/design-tokens' as *;
@use '../styles/variables' as v;

@use '../styles/list-filter-bar' as filterBar;

.hub-view {
  // FE-9365c: a normal scrolling page, matching Products/Projects. The old
  // `height: calc(100vh - 64px); overflow: hidden` existed to make a two-pane split
  // work; with one column and the thread as its own view there is nothing to trap.
  padding: 30px 40px 40px;

  @include filterBar.list-filter-bar;

  // General / Projects on their OWN row between the subtitle and the filter bar.
  &__tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 16px;
  }

  &__back-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  // The one accent strip. Yellow because it is the handover colour — and it exists
  // only when the baton points at the operator, so it is rare by construction.
  &__attention {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    width: 100%;
    max-width: 1120px;
    text-align: left;
    background: rgba(255, 195, 0, 0.07);
    --smooth-border-color: #{rgba($color-brand-yellow, 0.35)};
    border: none;
    border-radius: $border-radius-md; // 12
    padding: 10px 14px;
    margin-bottom: v.$spacing-md;
    cursor: pointer;
    font-size: 0.8125rem; // 13
    color: var(--text-secondary);

    strong { color: $color-text-primary; }
  }

  &__attention-icon { color: $color-brand-yellow; flex: none; }

  &__attention-text {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__attention-open {
    margin-left: auto;
    flex: none;
    font-weight: 600;
    color: $color-brand-yellow;
  }

  &__thread-meta {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    min-width: 0;
  }

  &__back {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: none;
    border: none;
    padding: 0;
    margin-bottom: v.$spacing-md;
    cursor: pointer;
    font-size: 0.8125rem; // 13
    color: var(--text-muted);
    transition: color $transition-fast;

    &:hover { color: $color-brand-yellow; }
  }

  &__main {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  &__thread-serial {
    flex: none;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.1875rem; // 19 — the header's louder cousin of the card's 15
    font-weight: 700;
    color: $color-brand-yellow;
    letter-spacing: 0.01em;
    margin-right: v.$spacing-sm;
  }

  &__thread-pills {
    display: flex;
    flex-wrap: wrap;
    gap: v.$spacing-xs;
    margin: v.$spacing-xs 0;
  }

  &__thread-head {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: v.$spacing-sm v.$spacing-md v.$spacing-md;
  }

  &__thread-title-row {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    min-height: 28px;
  }

  &__thread-title {
    font-family: 'Outfit', sans-serif;
    font-size: 1.0625rem; // 17
    font-weight: 600;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  &__thread-action {
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

  &__thread-rename {
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

  &__thread-rename-hint,
  &__thread-id-cmd { color: var(--text-muted); }
  &__thread-id-val { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  &__thread-id {
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

  &__thread-scope {
    display: flex;
    align-items: center;
    margin-left: auto; // right-aligned on the pill row, per the prototype
    flex: none;
    font-size: 0.71875rem; // 11.5
    color: var(--text-muted);
  }

  &__thread-id-cmd { color: var(--text-muted); }
  &__thread-id-val { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  &__thread-id {
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

  &__timeline {
    flex: 1;
    overflow-y: auto;
  }

  &__composer {
    flex-shrink: 0;
  }
}
</style>
