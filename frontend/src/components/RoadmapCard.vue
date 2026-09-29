<template>
  <div class="rm-card smooth-border">
    <div class="rm-rank">
      <div
        v-if="!isTerminal"
        class="rm-grip"
        role="button"
        :aria-label="`Drag to reorder ${displayTitle}`"
        title="Drag to reorder"
      ></div>
      <div
        v-else
        class="rm-grip-locked"
        aria-hidden="true"
        title="Locked — this item has reached a terminal state"
      >
        <v-icon icon="mdi-lock-outline" size="14" />
      </div>
      <span class="rm-num">{{ rank }}</span>
    </div>

    <div class="rm-body">
      <div class="rm-top">
        <span v-if="aliasShown" class="rm-alias" :style="aliasStyle">{{ item.taxonomy_alias }}</span>
        <span class="rm-title">{{ displayTitle }}</span>
      </div>

      <div class="rm-meta">
        <span class="rm-badge" :style="typeBadgeStyle">{{ typeLabel }}</span>
        <span v-if="statusBadge" class="rm-badge" :style="statusBadge.style">
          <v-icon :icon="statusBadge.icon" size="13" class="rm-badge-icon" />{{ statusBadge.label }}
        </span>
        <v-tooltip
          v-if="riskBadge"
          location="top"
          text="Chance this work causes problems or breaks things — low / med / high."
        >
          <template #activator="{ props: tipProps }">
            <span v-bind="tipProps" class="rm-badge" :style="riskBadge.style">
              <v-icon :icon="riskBadge.icon" size="13" class="rm-badge-icon" />{{ riskBadge.label }}
            </span>
          </template>
        </v-tooltip>
        <v-tooltip
          v-if="complexityBadge"
          location="top"
          text="Roughly how much effort to build — light / med / heavy."
        >
          <template #activator="{ props: tipProps }">
            <span v-bind="tipProps" class="rm-badge" :style="complexityBadge.style">
              <v-icon :icon="complexityBadge.icon" size="13" class="rm-badge-icon" />{{ complexityBadge.label }}
            </span>
          </template>
        </v-tooltip>
      </div>

      <div v-if="item.blocked" class="rm-blocked-row">
        <span class="rm-blocked-label">Blocked</span>
        <span v-if="item.blocked_reason" class="rm-blocked-reason">reason: {{ item.blocked_reason }}</span>
      </div>
    </div>

    <div class="rm-actions">
      <span
        v-if="isProject && inChain && !statusBadge"
        class="rm-badge rm-in-chain-pill"
        data-testid="roadmap-in-chain-pill"
      >
        <span class="mdi mdi-link-variant" aria-hidden="true" style="font-size: 11px; margin-right: 3px;" />
        In chain
      </span>
      <v-btn
        v-else-if="!isProject"
        variant="tonal"
        size="small"
        color="info"
        prepend-icon="mdi-folder-arrow-up-outline"
        class="rm-primary-btn rm-convert-btn"
        :disabled="isTerminal"
        :aria-label="`Convert task ${displayTitle} to a project`"
        @click="$emit('convert', item)"
      >
        Convert to Project
      </v-btn>

      <div class="rm-act-row">
        <v-tooltip location="top" :text="isProject ? 'Open project' : 'Open task'">
          <template #activator="{ props: tipProps }">
            <v-btn
              v-bind="tipProps"
              icon="mdi-eye-outline"
              variant="text"
              size="x-small"
              :aria-label="isProject ? 'Open project' : 'Open task'"
              @click="$emit('open', item)"
            />
          </template>
        </v-tooltip>
        <v-tooltip location="top" text="Demote to bottom">
          <template #activator="{ props: tipProps }">
            <v-btn
              v-bind="tipProps"
              icon="mdi-arrow-collapse-down"
              variant="text"
              size="x-small"
              aria-label="Demote to bottom"
              @click="$emit('demote', item)"
            />
          </template>
        </v-tooltip>
        <v-tooltip location="top" text="Remove from roadmap">
          <template #activator="{ props: tipProps }">
            <v-btn
              v-bind="tipProps"
              icon="mdi-close"
              variant="text"
              size="x-small"
              class="rm-remove-btn"
              :aria-label="`Remove ${displayTitle} from the roadmap`"
              @click="$emit('remove', item)"
            />
          </template>
        </v-tooltip>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { hexToRgba } from '@/utils/colorUtils'
import { getAgentColor } from '@/config/agentColors'
import { COLOR_BRAND, COLOR_COMPLETE, TEXT_MUTED } from '@/config/colorTokens'
import { taxonomyBadgeStyle, DEFAULT_PROJECT_TYPE_COLOR } from '@/utils/taxonomyBadge'

const props = defineProps({
  item: {
    type: Object,
    required: true,
  },
  rank: {
    type: Number,
    required: true,
  },
  inChain: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['convert', 'open', 'demote', 'remove'])

const isProject = computed(() => props.item.item_type === 'project')

const aliasShown = computed(() => !!(props.item.taxonomy_alias && props.item.taxonomy_alias.trim()))

const displayTitle = computed(() => props.item.title || '(untitled)')

const aliasStyle = computed(() =>
  taxonomyBadgeStyle(props.item.taxonomy_color || DEFAULT_PROJECT_TYPE_COLOR),
)

function tintedStyle(hex) {
  return {
    backgroundColor: hexToRgba(hex, 0.15),
    color: hex,
  }
}

const typeLabel = computed(() => (isProject.value ? 'PROJECT' : 'TASK'))
const typeBadgeStyle = computed(() =>
  tintedStyle(isProject.value ? COLOR_BRAND : getAgentColor('implementer').hex),
)

const RISK_MAP = {
  low: { label: 'LOW RISK', icon: 'mdi-shield-check', hex: COLOR_COMPLETE },
  med: { label: 'MED RISK', icon: 'mdi-shield-alert', hex: getAgentColor('tester').hex },
  high: { label: 'HIGH RISK', icon: 'mdi-shield-off', hex: getAgentColor('analyzer').hex },
}
const riskBadge = computed(() => {
  const r = RISK_MAP[props.item.risk]
  if (!r) return null
  return { label: r.label, icon: r.icon, style: tintedStyle(r.hex) }
})

const PROJECT_STATUS_BADGE = {
  active: { label: 'ACTIVATED', icon: 'mdi-rocket-launch-outline', hex: COLOR_BRAND },
  completed: { label: 'COMPLETED', icon: 'mdi-check-circle-outline', hex: COLOR_COMPLETE },
  cancelled: { label: 'CANCELLED', icon: 'mdi-cancel', hex: TEXT_MUTED },
  terminated: { label: 'CANCELLED', icon: 'mdi-cancel', hex: TEXT_MUTED },
  deleted: { label: 'DELETED', icon: 'mdi-delete-outline', hex: getAgentColor('analyzer').hex },
}
const TASK_STATUS_BADGE = {
  completed: { label: 'COMPLETED', icon: 'mdi-check-circle-outline', hex: COLOR_COMPLETE },
  cancelled: { label: 'CANCELLED', icon: 'mdi-cancel', hex: TEXT_MUTED },
}
const statusBadge = computed(() => {
  const map = isProject.value ? PROJECT_STATUS_BADGE : TASK_STATUS_BADGE
  const s = map[props.item.status]
  if (!s) return null
  return { label: s.label, icon: s.icon, style: tintedStyle(s.hex) }
})
const isTerminal = computed(() => statusBadge.value !== null)

const COMPLEXITY_MAP = {
  light: { label: 'LIGHT', icon: 'mdi-feather' },
  med: { label: 'MED', icon: 'mdi-weight' },
  heavy: { label: 'HEAVY', icon: 'mdi-weight' },
}
const complexityBadge = computed(() => {
  const c = COMPLEXITY_MAP[props.item.complexity]
  if (!c) return null
  return { label: c.label, icon: c.icon, style: tintedStyle(TEXT_MUTED) }
})

defineExpose({ isProject, aliasShown, aliasStyle, typeLabel, riskBadge, complexityBadge, statusBadge, isTerminal })
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;

.rm-card {
  display: flex;
  align-items: stretch;
  background: rgb(var(--v-theme-surface));
  border-radius: $border-radius-md;
  overflow: hidden;
  transition:
    transform $transition-normal ease,
    box-shadow $transition-normal ease;
}

.rm-card:hover {
  transform: translateY(-2px);
}

/* Rank rail: dotted grip + sort_order number */
.rm-rank {
  flex-shrink: 0;
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 12px;
  padding-right: 16px;
  box-shadow: inset -1px 0 0 var(--smooth-border-color, rgba(255, 255, 255, 0.06));
}

.rm-grip {
  align-self: stretch;
  width: 22px;
  cursor: grab;
  /* fine dotted pattern in the darker border-blue; brightens on hover */
  background:
    radial-gradient(var(--color-border) 0.9px, transparent 1.1px) 2px 2px / 4px 4px;
  transition: background $transition-fast ease;
}

.rm-grip:hover {
  background:
    radial-gradient(var(--color-agent-implementer) 0.9px, transparent 1.1px) 2px 2px /
    4px 4px;
}

.rm-grip:active {
  cursor: grabbing;
}

/* Terminal items are not reorderable — a muted, non-draggable lock replaces the
   dotted grip (no .rm-grip class, so SortableJS's handle selector can't grab it). */
.rm-grip-locked {
  align-self: stretch;
  width: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: default;
  color: var(--text-muted);
  opacity: 0.6;
}

.rm-num {
  font-family: ui-monospace, 'Cascadia Code', 'Roboto Mono', monospace;
  font-size: 1.4rem;
  font-weight: 600;
  color: var(--color-accent-primary);
}

/* FE-6165f: "In chain" pill (tinted badge — implementer blue). FE-9568
   (2026-09-02): read-only membership indicator now — the link-mode checkbox
   this used to sit alongside (.rm-link-mode-check) was removed. */
.rm-in-chain-pill {
  background-color: rgba(109, 179, 228, 0.15); /* var(--color-agent-implementer) at 15% */
  color: var(--color-agent-implementer);
}

/* Body */
.rm-body {
  flex: 1;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.rm-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.rm-alias {
  /* color + background come from the per-taxonomy tinted inline style
     (taxonomyBadgeStyle), matching the project/task list serial badges. */
  font-family: ui-monospace, 'Cascadia Code', 'Roboto Mono', monospace;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: $border-radius-sharp;
}

/* Blocked dependency row — red label (no icon) + free-text reason. */
.rm-blocked-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.rm-blocked-label {
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: $color-status-error;
}

.rm-blocked-reason {
  font-size: 0.78rem;
  color: var(--text-muted);
}

.rm-title {
  font-size: 1rem;
  font-weight: 600;
}

.rm-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.rm-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: $border-radius-default;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.rm-badge-icon {
  margin-right: 1px;
}

/* Action rail */
.rm-actions {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: center;
  gap: 8px;
  padding: 12px 14px;
  width: 188px;
  flex-shrink: 0;
  box-shadow: inset 1px 0 0 var(--smooth-border-color, rgba(255, 255, 255, 0.06));
}

.rm-primary-btn {
  text-transform: none;
  letter-spacing: 0;
  font-weight: 700;
}

.rm-act-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
}
</style>
