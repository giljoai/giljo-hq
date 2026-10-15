<template>
  <div class="hub-thread-frames">
    <div class="hub-thread-header__head smooth-border" data-testid="thread-header">
      <div class="hub-thread-header__title-row" data-testid="thread-header-row1">
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
            class="hub-thread-header__action hub-thread-header__copy"
            title="Copy join id: the thread id an agent passes to join_thread"
            aria-label="Copy join id"
            data-testid="thread-header-copy"
            @click="copyThreadId"
          >
            <v-icon size="16">mdi-content-copy</v-icon>
          </button>
          <button
            type="button"
            class="hub-thread-header__action"
            :title="resolveControl.label"
            :aria-label="resolveControl.label"
            data-testid="thread-header-resolve"
            @click="toggleResolved(commHub.selectedThread)"
          >
            <v-icon size="16">{{ resolveControl.icon }}</v-icon>
          </button>
        </template>
      </div>

      <div v-if="commHub.selectedThread" class="hub-thread-header__row2" data-testid="thread-header-row2">
        <span
          v-if="headerLocked && (projectAlias || showProjectName)"
          class="hub-thread-header__line"
          data-testid="thread-header-project"
        >
          <span
            v-if="projectAlias"
            class="hub-thread-header__project-badge"
            :style="projectBadgeStyle"
            data-testid="thread-header-project-badge"
          >{{ projectAlias }}</span>
          <span v-if="showProjectName" class="hub-thread-header__project-name">{{ projectLabel }}</span>
        </span>
        <span
          v-else-if="!headerLocked"
          class="hub-thread-header__line hub-thread-header__muted"
          data-testid="thread-header-general"
        >General</span>
        <span
          v-if="productLabel"
          class="hub-thread-header__line hub-thread-header__muted hub-thread-header__product"
          data-testid="thread-header-product"
        >{{ productLabel }}</span>
        <ThreadDates
          :thread="commHub.selectedThread"
          size="md"
          tinted
          dotted
          class="hub-thread-header__dates"
          data-testid="thread-header-dates"
        />
      </div>
    </div>

    <ThreadAgentRoster />
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { taxonomyBadgeStyle, resolveTaxonomyColor } from '@/utils/taxonomyBadge'
import { useToast } from '@/composables/useToast'
import { useClipboard } from '@/composables/useClipboard'
import { parseErrorResponse } from '@/utils/errorMessages'
import ThreadAgentRoster from '@/components/hub/ThreadAgentRoster.vue'
import ThreadDates from '@/components/hub/ThreadDates.vue'
import { threadResolveControl, useThreadResolve } from '@/components/hub/useThreadResolve'

const commHub = useCommHubStore()
const productStore = useProductStore()
const projectStore = useProjectStore()
const { showToast } = useToast()
const { copy } = useClipboard()
const { toggleResolved } = useThreadResolve()
const resolveControl = computed(() => threadResolveControl(commHub.selectedThread?.status))

const headerLocked = computed(() => commHub.selectedThread?.project_id != null)
const headerTitle = computed(() => {
  const t = commHub.selectedThread?.title || commHub.selectedThread?.subject
  return t || 'Untitled thread'
})

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

const thread = computed(() => commHub.selectedThread)
const product = computed(() => {
  const id = thread.value?.product_id
  if (!id) return null
  return productStore.products.find((p) => p.id === id) || productStore.getProductById(id)
})
const productLabel = computed(() => {
  if (!thread.value?.product_id) return ''
  return product.value?.name || 'unknown'
})
const project = computed(() => {
  const id = thread.value?.project_id
  return id ? projectStore.projectById(id) || null : null
})
const projectAlias = computed(() => project.value?.taxonomy_alias || '')
const projectLabel = computed(() => thread.value?.project_name || project.value?.name || headerTitle.value)
const normalizeTitle = (t) => String(t || '').trim().toLowerCase()
const showProjectName = computed(() => normalizeTitle(projectLabel.value) !== normalizeTitle(headerTitle.value))
const projectBadgeStyle = computed(() =>
  taxonomyBadgeStyle(
    resolveTaxonomyColor({
      abbreviation: project.value?.project_type?.abbreviation,
      alias: projectAlias.value,
      color: project.value?.project_type?.color,
    }),
  ),
)

watch(
  () => [thread.value?.product_id, thread.value?.project_id],
  ([productId, projectId]) => {
    if (productId && !product.value) productStore.fetchProductById(productId)
    if (projectId && !project.value) projectStore.fetchProject(projectId)
  },
  { immediate: true },
)

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
  // The main frame: a card in the roster frame's style, two rows.
  &__head {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: v.$spacing-sm v.$spacing-md;
    border-radius: $border-radius-md; // 12
    background: $elevation-raised;
  }

  &__title-row {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    min-height: 28px;
    min-width: 0;
  }

  &__serial {
    flex: none;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.9375rem; // 15
    font-weight: 700;
    color: $color-brand-yellow;
    letter-spacing: 0.01em;
  }

  &__title {
    min-width: 0;
    font-family: 'Outfit', sans-serif;
    font-size: 1rem; // 16
    font-weight: 500;
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

  // The copy control is an icon button in the action style, right after the lock.
  &__copy .v-icon { color: $color-brand-yellow; }

  &__rename {
    flex: 1;
    min-width: 0;
    font-family: 'Outfit', sans-serif;
    font-size: 1rem;
    font-weight: 500;
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.05);
    border: none;
    border-radius: $border-radius-md; // 12 — inputs
    padding: 4px 10px;

    &:focus { outline: none; }
  }

  &__rename-hint { color: var(--text-muted); }

  &__row2 {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px v.$spacing-sm;
    min-width: 0;
  }

  &__line {
    display: inline-flex;
    align-items: center;
    gap: v.$spacing-sm;
    min-width: 0;
    font-size: 0.8125rem; // 13
    color: var(--text-primary);
  }

  &__muted { color: var(--text-muted); }

  // A middle dot between every row 2 item; each item is a flex row, so its gap spaces the dot.
  &__row2 > * + *::before {
    content: '·';
    color: var(--text-muted);
  }

  &__project-badge {
    flex: none;
    padding: 1px 6px;
    border-radius: $border-radius-sharp;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem; // 12
    font-weight: 600;
  }

  &__project-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}
</style>
