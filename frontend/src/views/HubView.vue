<template>
  <v-container fluid class="hub-view pa-0" data-testid="hub-view">
    <template v-if="!commHub.selectedThreadId">
      <div class="hub-view__column">
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

      <div class="tab-pills hub-view__tabs main-window-reveal main-window-delay-2" role="tablist">
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
            class="filter-select hub-view__select"
            :style="selectWidthStyle(sortOptions)"
            :items="sortOptions"
            prepend-inner-icon="mdi-sort"
            variant="solo"
            density="compact"
            flat
            hide-details
            data-testid="hub-sort"
          />
          <v-select
            v-model="productScopeModel"
            class="filter-select hub-view__select"
            :style="selectWidthStyle(productScopeOptions)"
            :items="productScopeOptions"
            prepend-inner-icon="mdi-filter-variant"
            variant="solo"
            density="compact"
            flat
            hide-details
            data-testid="hub-product-scope"
          />
          <v-btn
            color="primary"
            variant="flat"
            icon="mdi-plus"
            title="New thread"
            aria-label="Create new thread"
            class="filter-cta-new"
            data-testid="new-thread-btn"
            @click="showNewThread = true"
          />
          <DeletedCountButton
            :count="deletedThreads.length"
            entity="threads"
            class="filter-cta-deleted"
            data-testid="deleted-threads-btn"
            @click="openDeletedThreads"
          />
        </div>

        <button
          v-if="activeTab === 'town' && attentionThread"
          type="button"
          class="hub-view__attention smooth-border"
          data-testid="hub-attention-strip"
          @click="openAttentionThread"
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
      </div>
    </template>

    <template v-else>
      <HubThreadToolbar v-model="messageSearch" @back="backToList" />
      <div class="hub-view__main">
          <HubThreadHeader />

        <ThreadTimeline
          class="hub-view__timeline"
          :search="messageSearch"
          :focus-message-id="focusMessageId"
          :focus-reason="focusReason"
        />
        <HubComposer class="hub-view__composer" />
      </div>
    </template>

    <NewThreadDialog
      v-model="showNewThread"
      @created="onThreadCreated"
    />

    <ThreadCreatedDialog
      v-model="showThreadCreated"
      :thread="createdThread"
    />

    <ThreadDeletedDialog
      v-model="showDeletedThreads"
      :deleted-threads="deletedThreads"
      :restoring-id="restoringId"
      @restore="onRestoreThread"
    />
  </v-container>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'
import { registerReconnectResync } from '@/stores/websocketEventRouter'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'
import { parseErrorResponse } from '@/utils/errorMessages'
import ThreadList from '@/components/hub/ThreadList.vue'
import DeletedCountButton from '@/components/common/DeletedCountButton.vue'
import ThreadTimeline from '@/components/hub/ThreadTimeline.vue'
import HubComposer from '@/components/hub/HubComposer.vue'
import HubThreadToolbar from '@/components/hub/HubThreadToolbar.vue'
import NewThreadDialog from '@/components/hub/NewThreadDialog.vue'
import ThreadCreatedDialog, { isThreadCreatedHintHidden } from '@/components/hub/ThreadCreatedDialog.vue'
import ThreadDeletedDialog from '@/components/hub/ThreadDeletedDialog.vue'
import {
  hubThreadRoute,
  resolveFocusMessageId,
  focusReasonOf,
} from '@/components/hub/hubThreadRoute'
import { threadDisplayName } from '@/components/hub/threadDisplayName'
import HubThreadHeader from '@/components/hub/HubThreadHeader.vue'

const commHub = useCommHubStore()
const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const { showToast } = useToast()
const showNewThread = ref(false)
const showThreadCreated = ref(false)
const createdThread = ref(null)
const showDeletedThreads = ref(false)
const deletedThreads = ref([])
const restoringId = ref(null)

const activeTab = ref('project')

const search = ref('')
const sort = ref('activity')
const sortOptions = [
  { title: 'Last activity', value: 'activity' },
  { title: 'Newest first', value: 'created' },
  { title: 'Serial', value: 'serial' },
]

const productScopeOptions = [
  { title: 'This product', value: 'viewed' },
  { title: 'All products', value: 'all' },
  { title: 'No product', value: 'unassigned' },
]
const productScopeModel = computed({
  get: () => commHub.productScope,
  set: (val) => commHub.setProductScope(val),
})

const SELECT_CHROME_PX = 84
function selectWidthStyle(options) {
  const longest = options.reduce((n, o) => Math.max(n, String(o.title || '').length), 0)
  return { width: `calc(${longest}ch + ${SELECT_CHROME_PX}px)` }
}

const messageSearch = ref('')
watch(() => commHub.selectedThreadId, () => { messageSearch.value = '' })


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

function backToList() {
  commHub.selectThread(null)
}


let unregisterResync = null

onMounted(async () => {
  await commHub.loadThreads()
  await loadDeletedThreads()

  await applyThreadDeepLink()

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
  commHub.selectThread(threadId)
  await commHub.loadThread(threadId)
  await commHub.loadParticipants(threadId)
}

function openAttentionThread() {
  if (!attentionThread.value) return
  router.push(hubThreadRoute(attentionThread.value))
}

async function applyThreadDeepLink() {
  if (route.query.tab === 'project' || route.query.tab === 'town') {
    activeTab.value = route.query.tab
  }
  const deepLinkThreadId = route.query.thread
  if (!deepLinkThreadId) return
  await onThreadSelect(deepLinkThreadId)
  const t = commHub.threadsById.get(deepLinkThreadId)
  if (t) activeTab.value = t.project_id != null ? 'project' : 'town'
}

watch(() => route.query.thread, (threadId) => { if (threadId) applyThreadDeepLink() })

const focusMessageId = computed(() =>
  resolveFocusMessageId(route.query, commHub.selectedThreadId, commHub.messagesFor(commHub.selectedThreadId)),
)

const focusReason = computed(() => focusReasonOf(route.query))

function onThreadCreated(thread) {
  if (thread?.thread_id) {
    commHub.selectThread(thread.thread_id)
    commHub.loadThread(thread.thread_id)
    commHub.loadParticipants(thread.thread_id)
    if (!isThreadCreatedHintHidden()) {
      createdThread.value = thread
      showThreadCreated.value = true
    }
  }
}

async function loadDeletedThreads({ notify = false } = {}) {
  try {
    const res = await api.threads.getDeleted()
    deletedThreads.value = res.data.threads ?? []
  } catch (err) {
    if (!notify) return
    const msg = parseErrorResponse(err).message || 'Failed to load deleted threads.'
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
    showToast({ type: 'success', message: `${threadDisplayName(thread)} restored.` })
    await commHub.loadThreads(commHub.filters)
  } catch (err) {
    const msg = parseErrorResponse(err).message || 'Failed to restore thread.'
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
  // FE-9593: below the tablet breakpoint the bar may wrap instead of squeezing the
  // search field to nothing — the shared mixin every other list view already uses.
  @include filterBar.list-filter-bar-responsive;

  // FE-9593: the selects no longer share the row's free width with the search field
  // (a `.v-input` is `flex: 1 1 auto` by default, which is what made both far wider
  // than their text). Their width is set per select from its longest option above.
  &__select {
    flex: 0 0 auto;
  }

  // FE-9368 (A): the list view's single column. 1120px is the card width FE-9365c
  // chose for readability; hanging the header, tabs, bar and cards off ONE cap is
  // what makes the bar and the cards line up instead of merely sitting near each
  // other. Centred, so the empty space is symmetrical on a wide monitor.
  &__column {
    max-width: 1120px;
    margin-inline: auto;
  }

  // General / Projects on their OWN row between the subtitle and the filter bar.
  &__tabs {
    display: flex;
    gap: 6px;
    margin-bottom: 16px;
  }

  // FE-9439: the back link, the in-thread search and the hand toggle moved to
  // HubThreadToolbar.vue with their styles — see that file for why.

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

  &__main {
    display: flex;
    flex-direction: column;
    min-height: 0;
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
