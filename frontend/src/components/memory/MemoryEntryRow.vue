<template>
  <div class="mem-row" :class="{ 'mem-row--open': expanded }" :data-test="`memory-row-${entry.id}`">
    <div
      class="mem-row-head"
      role="button"
      tabindex="0"
      :aria-expanded="expanded"
      @click="$emit('toggle')"
      @keydown.enter="$emit('toggle')"
      @keydown.space.prevent="$emit('toggle')"
    >
      <v-icon class="mem-row-chevron" :class="{ 'mem-row-chevron--open': expanded }" size="18">
        mdi-chevron-right
      </v-icon>

      <div class="mem-row-main">
        <div class="mem-row-summary">{{ summarySnippet }}</div>
        <div class="mem-row-meta">
          <span v-if="entry.project_name">{{ entry.project_name }}</span>
          <span v-if="entry.sequence != null"> · #{{ entry.sequence }}</span>
          <span v-if="entry.timestamp"> · {{ formattedDate }}</span>
          <span v-if="entry.author_name"> · {{ entry.author_name }}</span>
        </div>
      </div>

      <div class="mem-row-tags">
        <span
          v-if="entry.entry_type"
          class="mem-badge"
          :style="typeBadgeStyle(entry.entry_type)"
        >
          {{ typeLabel(entry.entry_type) }}
        </span>
        <span
          v-for="tag in entry.tags || []"
          :key="tag"
          class="mem-tag-chip"
          :style="tagChipStyle(tag)"
          :data-test="`memory-tag-${tag}`"
        >
          {{ tag }}
        </span>
      </div>
    </div>

    <div v-if="expanded" class="mem-row-body" :data-test="`memory-body-${entry.id}`">
      <div class="mem-markdown" v-html="renderedSummary"></div>

      <div v-if="(entry.key_outcomes || []).length" class="mem-section">
        <div class="mem-section-title">Key outcomes</div>
        <ul class="mem-list">
          <li v-for="(item, i) in entry.key_outcomes" :key="`ko-${i}`">{{ item }}</li>
        </ul>
      </div>

      <div v-if="(entry.decisions_made || []).length" class="mem-section">
        <div class="mem-section-title">Decisions made</div>
        <ul class="mem-list">
          <li v-for="(item, i) in entry.decisions_made" :key="`dm-${i}`">{{ item }}</li>
        </ul>
      </div>

      <div v-if="(entry.git_commits || []).length" class="mem-section">
        <div class="mem-section-title">Commits</div>
        <ul class="mem-list mem-list--mono">
          <li v-for="(commit, i) in entry.git_commits" :key="`gc-${i}`">
            <span v-if="commit.sha" class="mem-sha">{{ String(commit.sha).slice(0, 8) }}</span>
            {{ commitTrailingText(commit) }}
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { hexToRgba, getAgentBadgeStyle } from '@/utils/colorUtils'
import { getAgentColor } from '@/config/agentColors'
import { commitTitle } from '@/utils/gitCommitDisplay'

function commitTrailingText(commit) {
  if (commit.message) return commit.message
  return commit.sha ? '' : commitTitle(commit)
}

const props = defineProps({
  entry: { type: Object, required: true },
  expanded: { type: Boolean, default: false },
  renderedSummary: { type: String, default: '' },
})

defineEmits(['toggle'])

const summarySnippet = computed(() => {
  const s = props.entry.summary || 'No summary recorded.'
  return s.length > 160 ? `${s.slice(0, 160)}…` : s
})

const formattedDate = computed(() => {
  if (!props.entry.timestamp) return ''
  const d = new Date(props.entry.timestamp)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-US', { dateStyle: 'medium' })
})

const typeRoleMap = {
  project_completion: 'documenter',
  project_closeout: 'implementer',
  session_handover: 'reviewer',
  handover_closeout: 'analyzer',
  decision: 'reviewer',
  architecture: 'analyzer',
  discovery: 'tester',
  baseline: 'orchestrator',
}

function typeBadgeStyle(entryType) {
  return getAgentBadgeStyle(typeRoleMap[entryType] || 'tester')
}

function typeLabel(entryType) {
  return entryType ? entryType.replace(/_/g, ' ') : ''
}

const tagCategoryMap = {
  security: 'reviewer',
  'bug-fix': 'analyzer',
  bugfix: 'analyzer',
  bug: 'analyzer',
  architecture: 'analyzer',
  performance: 'tester',
  perf: 'tester',
  feature: 'implementer',
  refactor: 'implementer',
  docs: 'documenter',
  documentation: 'documenter',
  testing: 'tester',
  test: 'tester',
  infra: 'orchestrator',
  devops: 'orchestrator',
}
const PALETTE = ['orchestrator', 'analyzer', 'implementer', 'documenter', 'reviewer', 'tester']

function tagChipStyle(tag) {
  const key = String(tag).toLowerCase()
  let role = tagCategoryMap[key]
  if (!role) {
    let h = 0
    for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0
    role = PALETTE[h % PALETTE.length]
  }
  const hex = getAgentColor(role).hex
  return { backgroundColor: hexToRgba(hex, 0.15), color: hex }
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

// Flat list row inside the surface card: transparent, separated by the shared
// table-row separator mixin. Hover/open surfaces derive from the $color-surface
// token (no rgba literals).
.mem-row {
  @include table-row-separator;
  background: transparent;
  transition: background $transition-fast;

  &:last-child {
    border-bottom: none !important;
  }

  &:hover {
    background: rgba($color-surface, 0.03);
  }

  &--open {
    background: rgba($color-surface, 0.04);
  }
}

.mem-row-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  cursor: pointer;

  &:focus-visible {
    outline: 2px solid rgb(var(--v-theme-primary));
    outline-offset: -2px;
  }
}

.mem-row-chevron {
  margin-top: 1px;
  flex-shrink: 0;
  transition: transform $transition-fast ease;

  &--open {
    transform: rotate(90deg);
  }
}

.mem-row-main {
  flex: 1;
  min-width: 0;
}

.mem-row-summary {
  font-size: 0.82rem;
  line-height: 1.35;
  color: $color-text-primary;
}

.mem-row-meta {
  font-size: 0.62rem;
  color: var(--text-muted);
  font-family: 'IBM Plex Mono', monospace;
  margin-top: 3px;
}

.mem-row-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: flex-end;
  max-width: 45%;
  flex-shrink: 0;
}

// Canonical square tinted badge (§2): 8px radius from getAgentBadgeStyle inline
// style; geometry + type here. Reads like the Projects serial/status badge.
.mem-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: 0.58rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  white-space: nowrap;
}

// Canonical tinted pill chip (§3): pill radius, 0.15 tint from inline style.
.mem-tag-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: $border-radius-pill;
  font-size: 0.58rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.mem-row-body {
  padding: 4px 16px 16px 38px;
  border-top: 1px solid $color-border-tertiary;
}

.mem-section {
  margin-top: 12px;
}

.mem-section-title {
  // Shared muted-uppercase label, identical to the sibling data-table headers.
  @include table-header-label;
  margin-bottom: 4px;
}

.mem-list {
  margin: 0;
  padding-left: 18px;
  font-size: 0.78rem;
  line-height: 1.5;
  color: $color-text-primary;

  &--mono {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
  }
}

.mem-sha {
  color: $color-brand-yellow;
  margin-right: 6px;
}

.mem-markdown {
  font-size: 0.82rem;
  line-height: 1.6;
  color: $color-text-primary;

  :deep(h1),
  :deep(h2),
  :deep(h3) {
    font-size: 0.95rem;
    margin: 10px 0 6px;
  }

  :deep(p) {
    margin: 6px 0;
  }

  :deep(code) {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.74rem;
    background: rgba($color-surface, 0.06);
    padding: 1px 4px;
    border-radius: $border-radius-sharp;
  }

  :deep(pre) {
    // Recessed code surface: the flat elevation token, darker than the raised card.
    background: $elevation-flat;
    padding: 10px;
    border-radius: $border-radius-default;
    overflow-x: auto;
  }
}
</style>
