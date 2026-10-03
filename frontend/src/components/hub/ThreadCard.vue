<template>
  <div
    class="thread-card smooth-border"
    :class="{
      'thread-card--selected': selected,
      'thread-card--attention': attention,
      'thread-card--idle': isIdle,
    }"
    data-testid="thread-card"
    @click="$emit('open', thread.thread_id)"
  >
    <div class="thread-card__head">
      <template v-if="renaming">
        <input
          ref="renameInput"
          v-model="draft"
          class="thread-card__rename smooth-border"
          data-testid="thread-card-rename-input"
          @click.stop
          @keydown.enter.stop="saveRename"
          @keydown.esc.stop="cancelRename"
          @blur="cancelRename"
        />
        <span class="thread-card__rename-hint">↵ save · esc cancel</span>
      </template>

      <template v-else>
        <span class="thread-card__serial" data-testid="thread-card-serial">{{ serial }}</span>

        <v-icon
          v-if="thread._yourTurn"
          size="15"
          class="thread-card__hand"
          title="Waiting on you — an agent handed you the turn"
          data-testid="thread-card-hand"
        >mdi-hand-back-right-outline</v-icon>

        <span
          class="thread-card__title"
          :class="{ 'thread-card__title--unnamed': isUnnamed }"
          data-testid="thread-card-title"
        >
          {{ displayTitle }}
        </span>

        <div class="thread-card__actions" data-testid="thread-card-actions">
          <button
            v-if="!locked"
            type="button"
            class="thread-card__action"
            title="Rename"
            aria-label="Rename thread"
            data-testid="thread-card-rename"
            @click.stop="startRename"
          >
            <v-icon size="15">mdi-pencil-outline</v-icon>
          </button>
          <button
            type="button"
            class="thread-card__action"
            title="Copy thread id"
            aria-label="Copy thread id"
            data-testid="thread-card-copy"
            @click.stop="$emit('copy', thread)"
          >
            <v-icon size="15">mdi-content-copy</v-icon>
          </button>
          <button
            type="button"
            class="thread-card__action"
            :class="{ 'thread-card__action--danger': !locked }"
            :title="locked ? 'Kept with the project\'s 360 memory' : 'Delete'"
            :aria-label="locked ? 'Locked — kept with the project 360 memory' : 'Delete thread'"
            data-testid="thread-card-delete"
            @click.stop="locked ? $emit('lock-info', thread) : $emit('delete', thread)"
          >
            <v-icon size="15">{{ locked ? 'mdi-lock-outline' : 'mdi-trash-can-outline' }}</v-icon>
          </button>
        </div>
      </template>
    </div>

    <div class="thread-card__pills" data-testid="thread-card-pills">
      <span v-if="!agents.length" class="thread-card__empty-pills" data-testid="thread-card-empty-pills">
        No one has checked in yet — share the id so an agent can join.
      </span>
      <AgentPill
        v-for="a in visibleAgents"
        :key="a.participant_id"
        :participant="a"
        data-testid="thread-card-pill"
      />

      <span
        v-if="overflowLabel"
        class="thread-card__pill thread-card__pill--more smooth-border"
        :title="overflowTitle"
        data-testid="thread-card-pill-more"
      >
        {{ overflowLabel }}
      </span>

      <span
        class="thread-card__pill thread-card__pill--more smooth-border"
        :title="productChipTitle"
        data-testid="thread-card-product-chip"
      >
        <v-icon size="12">mdi-cube-outline</v-icon>
        {{ productChipLabel }}
      </span>
      <span
        v-if="projectTagCount > 0"
        class="thread-card__pill thread-card__pill--more smooth-border"
        :title="projectTagTitle"
        data-testid="thread-card-project-chip"
      >
        <v-icon size="12">mdi-folder-outline</v-icon>
        {{ projectTagCount === 1 ? '1 project' : `${projectTagCount} projects` }}
      </span>

      <span
        v-if="isTerminal"
        class="thread-card__status smooth-border"
        :style="statusStyle"
        :title="statusTitle"
        data-testid="thread-card-status"
      >
        {{ thread.status }}
      </span>
    </div>

    <div v-if="thread.last_message" class="thread-card__last" data-testid="thread-card-last">
      <span class="thread-card__last-author">{{ thread.last_message.author }}:</span>
      {{ excerpt }}
    </div>

    <div class="thread-card__foot">
      <button
        type="button"
        class="thread-card__join"
        title="Copy thread id"
        data-testid="thread-card-join"
        @click.stop="$emit('copy', thread)"
      >
        <span class="thread-card__join-cmd">join_thread</span>
        <span class="thread-card__join-id">{{ thread.thread_id }}</span>
        <v-icon size="13">mdi-content-copy</v-icon>
      </button>
      <span v-if="locked" class="thread-card__lock-note">· kept with the project's 360 memory</span>

      <ThreadDates :thread="thread" size="sm" class="thread-card__dates" data-testid="thread-card-dates" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { getAgentColor } from '@/config/agentColors'
import { tintedStyle } from '@/utils/colorUtils'
import { useProductStore } from '@/stores/products'
import { BOUND_THREAD_MARKER_SUBJECT } from '@/composables/useProjectBoundThread'
import AgentPill from '@/components/hub/AgentPill.vue'
import ThreadDates from '@/components/hub/ThreadDates.vue'

const props = defineProps({
  thread: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})

const emit = defineEmits(['open', 'rename', 'copy', 'delete', 'lock-info'])

const locked = computed(() => props.thread.project_id != null)

const productStore = useProductStore()
const productChipLabel = computed(() => {
  const pid = props.thread.product_id
  if (!pid) return 'No product'
  return productStore.getProductById(pid)?.name || 'Product'
})
const productChipTitle = computed(() =>
  props.thread.product_id ? `Product: ${productChipLabel.value}` : 'No product tagged',
)
const projectTagCount = computed(() => (props.thread.project_ids || []).length)
const projectTagTitle = computed(() => `Tagged to ${projectTagCount.value} project(s)`)

const displayTitle = computed(() => {
  const t = props.thread.title || props.thread.subject
  return isUnnamed.value ? 'Untitled thread' : t
})
const isUnnamed = computed(() => {
  const t = props.thread.title || props.thread.subject
  return !t || t === BOUND_THREAD_MARKER_SUBJECT
})

const agents = computed(() => (props.thread.participants || []).filter((p) => p.participant_type !== 'user'))

const MAX_PILLS = 5
const visibleAgents = computed(() => agents.value.slice(0, MAX_PILLS))
const overflowAgents = computed(() => agents.value.slice(MAX_PILLS))

const overflowLabel = computed(() =>
  overflowAgents.value.length > 0 ? `+${overflowAgents.value.length} more` : '',
)

const overflowTitle = computed(() =>
  overflowAgents.value
    .map((a) => `${a.display_name || a.participant_id} · ${harnessLabel(a.harness)}`)
    .join('\n'),
)

function harnessLabel(harness) {
  if (!harness || harness === 'generic') return 'Generic Harness'
  return String(harness).split(' · ')[0]
}

const excerpt = computed(() => {
  const raw = props.thread.last_message?.excerpt || ''
  return raw.length > 160 ? `${raw.slice(0, 160)}…` : raw
})

const serial = computed(() => props.thread.chat_id || '')
const TERMINAL = new Set(['resolved', 'closed'])
const isTerminal = computed(() => TERMINAL.has(String(props.thread.status || '').toLowerCase()))
const statusStyle = computed(() => tintedStyle(getAgentColor('reviewer')?.hex))

const STATUS_MEANINGS = {
  resolved: "resolved: the agents agreed it's done; still readable",
  closed: 'closed: accepted by the orchestrator, final',
}
const statusTitle = computed(() => STATUS_MEANINGS[String(props.thread.status || '').toLowerCase()] || '')

const attention = computed(() => !!props.thread._yourTurn)
const isIdle = computed(() => isTerminal.value)


const renaming = ref(false)
const draft = ref('')
const renameInput = ref(null)

async function startRename() {
  draft.value = props.thread.subject || ''
  renaming.value = true
  await nextTick()
  renameInput.value?.focus()
  renameInput.value?.select()
}

function saveRename() {
  const next = draft.value.trim()
  renaming.value = false
  if (next && next !== props.thread.subject) emit('rename', { thread: props.thread, subject: next })
}

function cancelRename() {
  renaming.value = false
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

.thread-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 20px;
  margin-bottom: 12px;
  border-radius: $border-radius-rounded; // 16 — cards
  background: $elevation-raised;
  cursor: pointer;
  transition: transform $transition-base, background $transition-base, box-shadow $transition-base;

  &:hover {
    background: $elevation-elevated;
    --smooth-border-color: #{rgba(255, 255, 255, 0.14)};
    box-shadow: $shadow-card-hover;
    transform: translateY(-2px);

    .thread-card__actions { opacity: 1; pointer-events: auto; }
  }

  @media (prefers-reduced-motion: reduce) {
    transition: background $transition-base;
    &:hover { transform: none; }
  }

  // Waiting on you: yellow fill + accent ring, title brightens. No extra chip.
  &--attention:not(.thread-card--selected) {
    background: rgba($color-brand-yellow, 0.07);
    --smooth-border-color: #{rgba($color-brand-yellow, 0.4)};
    .thread-card__title { color: #fff; }
  }

  &--selected {
    --smooth-border-color: #{rgba($color-brand-yellow, 0.4)};
    background: rgba($color-brand-yellow, 0.07);
  }

  &--idle { opacity: 0.75; }

  &__head {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    min-height: 22px;
    // FE-9365c — RESERVE the strip the hover actions occupy.
    //
    // `__actions` is absolutely positioned at `right: 20px`, so it is out of flow and
    // the title, being `flex: 1`, truncated at the FULL card width. On hover the three
    // buttons were therefore drawn directly ON TOP of the title's last words. Worst in
    // a narrow column, which is why it survived review — reported live 2026-08-04.
    //
    // Padding rather than a width on `__title`: it keeps the actions out of flow, so
    // the no-layout-shift property still holds (the fading `__time` occupies the same
    // reserved strip), while the title now runs out of room BEFORE the buttons start.
    // 3 buttons x 26px + 2 gaps x 4px + the 20px right offset. (FE-9593: the relative
    // time that used to share this strip is gone; the strip stays reserved for them.)
    padding-right: 106px;
  }

  &__hand {
    flex: none;
    color: $color-brand-yellow;
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
    flex: 1;
    min-width: 0;
    font-family: 'Outfit', sans-serif;
    font-size: 1rem; // 16
    font-weight: 600;
    color: $color-text-primary;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    &--unnamed { font-style: italic; color: var(--text-muted, #{$color-text-secondary}); }
  }

  &__actions {
    display: flex;
    gap: v.$spacing-xs;
    opacity: 0;
    pointer-events: none;
    transition: opacity $transition-fast;
    position: absolute;
    top: 16px;
    right: 20px;
  }

  &__action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border: none;
    background: transparent;
    color: var(--text-muted, #{$color-text-secondary});
    border-radius: $border-radius-default; // 8
    cursor: pointer;
    transition: color $transition-fast, background $transition-fast;

    &:hover { color: $color-text-primary; background: rgba(255, 255, 255, 0.08); }
    &--danger:hover { color: $color-accent-danger; background: rgba($color-accent-danger, 0.12); }
  }

  &__rename {
    flex: 1;
    min-width: 0;
    font-family: 'Outfit', sans-serif;
    font-size: 1rem;
    font-weight: 600;
    color: $color-text-primary;
    background: $elevation-elevated;
    border: none;
    border-radius: $border-radius-md; // 12 — inputs
    padding: 4px 10px;
    --smooth-border-color: #{rgba($color-brand-yellow, 0.4)};

    &:focus { outline: none; }
  }

  &__rename-hint {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem;
    color: var(--text-muted, #{$color-text-secondary});
    white-space: nowrap;
  }

  &__pills {
    display: flex;
    flex-wrap: wrap;
    gap: v.$spacing-xs;
  }

  &__empty-pills {
    font-size: 0.75rem; // 12
    color: var(--text-muted, #{$color-text-secondary});
    font-style: italic;
  }

  &__pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 8px 3px 4px;
    border-radius: $border-radius-default; // 8
    background: rgba(255, 255, 255, 0.03);
    --smooth-border-color: #{rgba(255, 255, 255, 0.10)};
    // A pill can never grow past this, so five of them cost a predictable width and a
    // five-agent card is the same height as a one-agent card.
    max-width: 220px;
    min-width: 0;

    &--more {
      padding: 3px 8px;
      font-family: 'IBM Plex Mono', monospace;
      font-size: 0.6875rem; // 11 — floor
      color: var(--text-muted, #{$color-text-secondary});
      cursor: default;
    }
  }

  &__last {
    font-size: 0.8125rem; // 13
    color: var(--text-secondary, #{$color-text-secondary});
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  &__last-author { color: var(--text-muted, #{$color-text-secondary}); font-weight: 600; }

  &__foot {
    display: flex;
    align-items: center;
    // FE-9593: the dates ride this row and wrap under the join block when the card
    // is narrow (tablet band), rather than clipping either.
    flex-wrap: wrap;
    gap: v.$spacing-sm;
    min-width: 0;
  }

  // FE-9593: the dates sit right-aligned when the row has room and wrap under the join
  // block on a narrow card.
  &__dates { margin-left: auto; }

  // The terminal block that replaced the truncated id. Same shape the thread view
  // shows, so the operator learns one thing and uses it in both places.
  &__join {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    background: var(--bg-terminal, #0d1117);
    border: none;
    border-radius: $border-radius-default; // 8
    padding: 7px 11px;
    cursor: pointer;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.71875rem; // 11.5
    color: $color-text-secondary;

    .thread-card__join-cmd { color: var(--text-muted, #{$color-text-secondary}); }
    .thread-card__join-id { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .v-icon { color: $color-brand-yellow; flex: none; }

    &:hover { background: rgba(255, 255, 255, 0.05); }
  }

  &__lock-note {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem; // 11 — floor
    color: var(--text-muted, #{$color-text-secondary});
    white-space: nowrap;
  }



  &__status {
    font-size: 0.6875rem; // 11 — floor
    font-weight: 600;
    padding: 1px 8px;
    border-radius: $border-radius-default; // 8
    text-transform: capitalize;
  }
}
</style>
