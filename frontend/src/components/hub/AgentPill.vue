<template>
  <span class="agent-pill smooth-border" :title="pillTitle">
    <span class="agent-pill__badge" :style="badgeStyle">{{ initials }}</span>
    <span class="agent-pill__harness">{{ harness }}</span>
    <span class="agent-pill__dot" :style="dotStyle" :title="dot.label" />
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { getAgentColor, getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { agentStatusDot, agentPillTitle } from '@/composables/useAgentStatusDot'

const props = defineProps({
  participant: { type: Object, required: true },
})

const harness = computed(() => {
  const h = props.participant.harness
  if (!h || h === 'generic') return 'Generic Harness'
  return String(h).split(' · ')[0]
})

const initials = computed(() => {
  const name = props.participant.display_name || props.participant.participant_id || '?'
  return getAgentInitials(name)
})

const badgeStyle = computed(() => {
  const { hex } = getAgentColor(getAgentColorKey(props.participant))
  return { backgroundColor: hexToRgba(hex, 0.2), color: hex }
})

const dot = computed(() => agentStatusDot(props.participant))
const dotStyle = computed(() => ({ backgroundColor: dot.value.color, boxShadow: dot.value.ring }))
const pillTitle = computed(() => agentPillTitle(props.participant, harness.value))
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.agent-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px 3px 4px;
  border-radius: $border-radius-default; // 8
  background: rgba(255, 255, 255, 0.03);
  --smooth-border-color: #{rgba(255, 255, 255, 0.10)};
  // Bounded so five pills cost a predictable width; only the harness may shrink.
  max-width: 220px;
  min-width: 0;

  &__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none; // the badge IS the identity — it never collapses
    width: 18px;
    height: 18px;
    border-radius: $border-radius-default;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem; // 11 — floor
    font-weight: 700;
  }

  &__harness {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.71875rem; // 11.5
    color: var(--text-secondary, #{$color-text-secondary});
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  // Round by design — a status dot, the standing exception to the square rule.
  // Colour and ring come from useAgentStatusDot: the Jobs board's vocabulary.
  &__dot {
    flex: none;
    width: 7px;
    height: 7px;
    border-radius: 50%;
  }
}
</style>
