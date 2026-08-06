<!--
  IndicatorLegend.vue — FE-9365e, reshaped to the reviewed prototype (FE-9365f)

  "What the indicators mean" — a floating panel anchored to the right edge, beside the
  cards rather than above them. The prototype renders it this way for a reason the
  block version got wrong: a full-width section pushes every card down when opened,
  which punishes the operator for asking a question. The panel lives in the dead space
  right of the 1120px column and covers nothing at typical widths.

  The rule this panel enforces: a user should never have to guess what a colour means.
  If the legend cannot explain an indicator in one line, the indicator should not exist.

  Every swatch is DERIVED from useAgentStatusDot / statusConfig.js rather than
  hand-written. A copied hex table is a second source of truth that starts correct and
  drifts silently — the dot changes, the legend keeps explaining the old colour, and
  the operator is worse off than with no legend at all. The spec enforces this by
  failing on any hex literal in this script block.
-->
<template>
  <aside class="legend smooth-border" data-testid="indicator-legend">
    <div class="legend__titlebar">
      <h2 class="legend__title">What the indicators mean</h2>
      <button
        type="button"
        class="legend__close"
        title="Close"
        aria-label="Close the legend"
        data-testid="legend-close"
        @click="$emit('close')"
      >
        <v-icon size="16">mdi-close</v-icon>
      </button>
    </div>

    <p class="legend__intro">
      The dot on an agent pill is the <strong>same status vocabulary as the Jobs
      dashboard</strong> — identical hexes from <code>statusConfig.js</code>. Nothing on
      this screen invents a colour.
    </p>

    <h3 class="legend__heading">Agent status dot</h3>
    <ul class="legend__rows">
      <li v-for="row in statusRows" :key="row.key" class="legend__row" data-testid="legend-status-row">
        <span class="legend__dot" :style="{ backgroundColor: row.color, boxShadow: row.ring }" />
        <span class="legend__label">{{ row.label }}</span>
        <code class="legend__hex">{{ row.hex }}</code>
        <span class="legend__meaning">{{ row.meaning }}</span>
      </li>
    </ul>

    <h3 class="legend__heading">Thread status chip</h3>
    <ul class="legend__rows">
      <li v-for="row in threadRows" :key="row.label" class="legend__row">
        <span class="legend__chip" :style="row.style">{{ row.label }}</span>
        <span class="legend__meaning">{{ row.meaning }}</span>
      </li>
    </ul>

    <h3 class="legend__heading">Everything else on a card</h3>
    <ul class="legend__rows">
      <li v-for="row in cardRows" :key="row.label" class="legend__row">
        <span class="legend__label legend__label--wide">{{ row.label }}</span>
        <span class="legend__meaning">{{ row.meaning }}</span>
      </li>
    </ul>

    <h3 class="legend__heading">Two things this screen will not do</h3>
    <ul class="legend__rows">
      <li class="legend__row">
        <span class="legend__label legend__label--wide">Never interprets a post</span>
        <span class="legend__meaning">
          The preview is the last message verbatim. Nothing here summarises,
          keyword-matches or re-writes what an agent wrote.
        </span>
      </li>
      <li class="legend__row">
        <span class="legend__label legend__label--wide">Never guesses your turn</span>
        <span class="legend__meaning">
          "Waiting on you" comes only from the baton pointing at you. However urgently a
          post asks, if no agent handed you the turn the card stays grey.
        </span>
      </li>
    </ul>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { agentStatusDot } from '@/composables/useAgentStatusDot'
import { getAgentColor } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'

defineEmits(['close'])

// One row per state the dot can actually reach. The meaning column is the operator's,
// not the enum's — "blocked" is a state name, "stuck on something it cannot decide" is
// what they need to know.
const STATUS_MEANINGS = [
  ['waiting', 'Posted and expecting a reply'],
  ['working', 'Actively running in its harness'],
  ['blocked', 'Stuck on something it cannot decide'],
  ['awaiting_user', 'Handed the call to you. Drives the yellow card'],
  ['complete', 'Finished its part of the work'],
  ['idle', 'Registered, watching, not working'],
  ['sleeping', 'Session parked, will resume'],
  ['handed_over', 'Passed its work to a successor'],
  ['closed', 'Accepted by the orchestrator'],
  ['decommissioned', 'Retired after succession'],
]

// Colour, ring and label all come from the composable the DOTS use, so the legend
// cannot describe a colour the card does not render.
const statusRows = computed(() => {
  const rows = STATUS_MEANINGS.map(([key, meaning]) => {
    const dot = agentStatusDot({ status: key, last_seen_at: 'seen' })
    return { key, meaning, color: dot.color, ring: dot.ring, label: dot.label, hex: dot.color }
  })

  const never = agentStatusDot({ status: null, last_seen_at: null })
  rows.push({
    key: 'never',
    meaning: 'Holds the id but has not registered yet',
    color: never.color,
    ring: never.ring,
    label: never.label,
    hex: '—',
  })
  return rows
})

function chipStyle(role) {
  const hex = getAgentColor(role)?.hex
  return { backgroundColor: hexToRgba(hex, 0.15), color: hex }
}

const threadRows = computed(() => [
  { label: 'resolved', meaning: "Agents agreed it's done. Still readable", style: chipStyle('reviewer') },
  { label: 'closed', meaning: 'Finality — accepted by the orchestrator', style: chipStyle('reviewer') },
  {
    label: 'open',
    // Its absence is a decision, not a bug: almost every thread is open, so a chip
    // saying so would appear on all of them and mean nothing.
    meaning: 'Never rendered — the default needs no chip',
    style: { backgroundColor: 'rgba(255, 255, 255, 0.06)', color: 'var(--text-muted)' },
  },
])

const cardRows = [
  { label: 'CHT-#### (yellow)', meaning: "The thread's handle — the id you quote to an agent. Bold, in front of the name" },
  { label: 'Role badge', meaning: "The agent's identity and role colour. Hover it for the full name — agent names are long and unstable" },
  { label: 'Harness label', meaning: 'Which tool that agent registered from, model suffix stripped' },
  { label: 'Yellow card + strip', meaning: 'Handover to you — read from the baton only, never from the words in a post' },
  { label: '+N more', meaning: 'Agents beyond the first five. Hover to see who' },
  { label: 'join_thread block', meaning: 'Click to copy the full id so another agent can join' },
  { label: 'Lock icon', meaning: "A project's audit log — named after its project, kept with its 360 memory" },
  { label: 'direct chip', meaning: 'That post went to one agent, not the whole thread' },
]
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

.legend {
  // The prototype's placement: a fixed panel in the dead space right of the 1120px
  // card column. It floats over nothing at typical widths and never reflows the list.
  position: fixed;
  top: 76px;
  right: 24px;
  width: 372px;
  max-height: calc(100vh - 100px);
  overflow-y: auto;
  z-index: 40;

  background: $elevation-raised;
  border-radius: $border-radius-rounded; // 16
  padding: v.$spacing-md v.$spacing-lg;
  display: flex;
  flex-direction: column;
  gap: v.$spacing-sm;

  &__titlebar {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__title {
    font-family: 'Outfit', sans-serif;
    font-size: 0.9375rem; // 15
    font-weight: 600;
    color: $color-text-primary;
  }

  &__close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border: none;
    background: transparent;
    color: var(--text-muted);
    border-radius: $border-radius-default; // 8 — a button, so a rounded square
    cursor: pointer;

    &:hover { color: $color-text-primary; background: rgba(255, 255, 255, 0.08); }
  }

  &__intro {
    font-size: 0.75rem; // 12
    color: var(--text-secondary);
    line-height: 1.5;
    margin: 0;

    code {
      font-family: 'IBM Plex Mono', monospace;
      font-size: 0.6875rem;
      color: var(--text-muted);
    }
  }

  // The prototype's section headers: small mono caps, quiet.
  &__heading {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem; // 11 — the floor
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin: v.$spacing-xs 0 0;
  }

  &__rows {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }

  &__row {
    display: flex;
    align-items: baseline;
    gap: v.$spacing-sm;
    font-size: 0.75rem; // 12
  }

  // Round — a status dot, the standing exception to the square-button rule.
  &__dot {
    align-self: center;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex: none;
  }

  &__label {
    min-width: 108px;
    color: var(--text-secondary);
    font-weight: 600;
    flex: none;

    &--wide { min-width: 128px; }
  }

  &__hex {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem;
    color: var(--text-muted);
    min-width: 64px;
    flex: none;
  }

  &__chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 1px 8px;
    border-radius: $border-radius-pill;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem;
    min-width: 76px;
    flex: none;
  }

  &__meaning {
    color: var(--text-muted);
    line-height: 1.45;
    min-width: 0;
  }
}
</style>
