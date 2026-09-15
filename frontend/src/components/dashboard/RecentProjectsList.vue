<template>
  <div class="recent-projects-list">
    <div v-if="projects.length === 0" class="no-data-text">
      No completed projects yet
    </div>
    <div v-else class="projects-scroll">
      <div
        v-for="project in projects"
        :key="project.id"
        class="project-row"
        @click="emit('review-project', project)"
      >
        <span v-if="project.taxonomy_alias" class="project-taxonomy" :style="taxonomyStyle(project)">
          {{ project.taxonomy_alias }}
        </span>
        <span class="project-name">
          {{ project.name }}
          <span v-if="project.product_name" class="project-product">({{ project.product_name }})</span>
        </span>
        <span class="project-time">{{ formatDateTime(project.completed_at) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useFormatDate } from '@/composables/useFormatDate'
import { TEXT_MUTED_MATERIAL } from '@/config/colorTokens'
import { isReservedTaskAlias } from '@/utils/taxonomyBadge'
import { TSK_TYPE_COLOR } from '@/utils/constants'

const { formatDateTime } = useFormatDate()

defineProps({
  projects: {
    type: Array,
    default: () => [],
  },
})

const emit = defineEmits(['review-project'])

function hexToRgb(hex) {
  const h = hex.replace('#', '')
  return `${parseInt(h.substring(0, 2), 16)}, ${parseInt(h.substring(2, 4), 16)}, ${parseInt(h.substring(4, 6), 16)}`
}

function taxonomyStyle(project) {
  const color = isReservedTaskAlias(project.taxonomy_alias)
    ? TSK_TYPE_COLOR
    : project.project_type_color || TEXT_MUTED_MATERIAL
  return {
    background: `rgba(${hexToRgb(color)}, 0.15)`,
    color,
  }
}

</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.projects-scroll {
  max-height: 340px;
  overflow-y: auto;
}

.project-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid $color-border-tertiary;
  transition: background $transition-fast;
  cursor: pointer;

  &:last-child {
    border-bottom: none;
  }

  &:hover {
    background: rgba(255, 255, 255, 0.02);
    margin: 0 -18px;
    padding: 10px 18px;
  }
}

.project-taxonomy {
  padding: 2px 8px;
  border-radius: $border-radius-sharp;
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  flex-shrink: 0;
  min-width: 48px;
  text-align: center;
}

.project-name {
  flex: 1;
  font-size: 0.78rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: $color-text-primary;
}

.project-product {
  font-size: 0.68rem;
  color: var(--text-muted);
  margin-left: 4px;
}

.project-time {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem;
  color: var(--text-muted);
  flex-shrink: 0;
  min-width: 56px;
  text-align: right;
}

.project-status {
  padding: 2px 8px;
  border-radius: $border-radius-pill;
  font-size: 0.58rem;
  font-weight: 700;
  text-transform: capitalize;
  flex-shrink: 0;
  min-width: 68px;
  text-align: center;

  &.active { background: $color-surface; color: $color-text-dark; }
  &.inactive { background: $color-text-muted; color: $color-text-on-muted; }
  &.completed { background: $color-status-complete; color: $color-background-primary; }
  &.cancelled { background: $color-brand-yellow; color: $color-background-primary; }
  &.terminated { background: $color-status-failed; color: $color-text-primary; }
  &.staged { background: $color-status-staged; color: $color-background-primary; }
}

.no-data-text {
  font-size: 0.75rem;
  color: var(--text-muted);
  padding: 8px 0;
  text-align: center;
}
</style>
