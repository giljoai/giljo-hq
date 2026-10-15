<template>
  <section
    v-if="commHub.selectedThread"
    class="thread-roster smooth-border"
    data-testid="thread-roster"
  >
    <div class="thread-roster__head" data-testid="thread-roster-head">
      <span class="thread-roster__title">Agents</span>
      <span class="thread-roster__counts">
        · {{ agents.length }} on this thread · {{ activeCount }} active<template
          v-if="collapsed && needYou.size > 0"
        > · <span class="thread-roster__need">{{ needYou.size }} need you</span></template>
      </span>
      <button
        type="button"
        class="thread-roster__toggle"
        :aria-expanded="!collapsed"
        data-testid="thread-roster-toggle"
        @click="toggle"
      >
        {{ collapsed ? 'Expand' : 'Collapse' }}
        <v-icon size="14">{{ collapsed ? 'mdi-chevron-down' : 'mdi-chevron-up' }}</v-icon>
      </button>
    </div>

    <template v-if="!collapsed">
      <div v-if="agents.length" class="thread-roster__grid">
        <div
          v-for="a in agents"
          :key="a.participant_id"
          class="thread-roster__tile smooth-border"
          :title="tileTitle(a)"
          data-testid="thread-roster-tile"
        >
          <span
            class="thread-roster__avatar"
            :style="avatarStyle(a)"
            aria-hidden="true"
            data-testid="thread-roster-avatar"
          >{{ initials(a) }}</span>
          <span class="thread-roster__who">
            <span class="thread-roster__name" data-testid="thread-roster-name">{{ nameOf(a) }}</span>
            <span class="thread-roster__sub" data-testid="thread-roster-sub">{{ harnessLabel(a.harness) }} · {{ stateWords(a, commHub.selectedThread) }}</span>
          </span>
          <span class="thread-roster__dot" :style="dotStyle(a)" />
        </div>
      </div>

      <div class="thread-roster__scope" data-testid="thread-roster-scope">
        <v-icon v-if="locked" size="13" class="mr-1">mdi-eye-off-outline</v-icon>
        {{ scopeNote }}
      </div>
    </template>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useCommHubStore } from '@/stores/commHubStore'
import { useUserStore } from '@/stores/user'
import { getAgentColor, getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'
import { agentStatusDot, agentPillTitle } from '@/composables/useAgentStatusDot'
import { harnessLabel, rosterAgents, stateWords, isActive, needYouIds } from '@/components/hub/rosterState'

const COLLAPSED_KEY = 'giljo.hub.threadRoster.collapsed'

const commHub = useCommHubStore()
const userStore = useUserStore()

function readCollapsed() {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

const collapsed = ref(readCollapsed())

function toggle() {
  collapsed.value = !collapsed.value
  try {
    localStorage.setItem(COLLAPSED_KEY, collapsed.value ? '1' : '0')
  } catch {
    // Storage unavailable: the choice holds for this page load only.
  }
}

const thread = computed(() => commHub.selectedThread)
const agents = computed(() => rosterAgents(commHub.participantsFor(commHub.selectedThreadId || '')))
const activeCount = computed(() => agents.value.filter((a) => isActive(a, thread.value)).length)
const needYou = computed(() =>
  needYouIds(
    commHub.participantsFor(commHub.selectedThreadId || ''),
    thread.value,
    commHub.messagesFor(commHub.selectedThreadId || ''),
    userStore.currentUser?.id,
  ),
)

const locked = computed(() => thread.value?.project_id != null)
const scopeNote = computed(() =>
  locked.value
    ? "Kept with the project record — not part of an agent's working context."
    : 'Visible to the agents registered here, on their next poll',
)

const nameOf = (a) => a.display_name || a.participant_id || 'Unnamed agent'
const initials = (a) => getAgentInitials(nameOf(a))

function avatarStyle(a) {
  const { hex } = getAgentColor(getAgentColorKey(a))
  return { backgroundColor: hexToRgba(hex, 0.2), color: hex }
}

function dotStyle(a) {
  const dot = agentStatusDot(a)
  return { backgroundColor: dot.color, boxShadow: dot.ring }
}

const tileTitle = (a) => agentPillTitle(a, harnessLabel(a.harness))
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;
@use '../../styles/variables' as v;

.thread-roster {
  display: flex;
  flex-direction: column;
  gap: v.$spacing-sm;
  margin-top: 8px;
  padding: v.$spacing-sm v.$spacing-md;
  border-radius: $border-radius-md; // 12
  background: $elevation-raised;

  &__head {
    display: flex;
    align-items: baseline;
    gap: v.$spacing-xs;
    min-width: 0;
  }

  &__title {
    font-family: 'Outfit', sans-serif;
    font-size: 0.875rem; // 14
    font-weight: 600;
    color: var(--text-primary);
  }

  &__counts {
    font-size: 0.75rem; // 12
    color: var(--text-muted);
  }

  &__need {
    color: $color-brand-yellow;
    font-weight: 600;
  }

  &__toggle {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 2px 6px;
    border: none;
    border-radius: $border-radius-default;
    background: transparent;
    font-size: 0.75rem; // 12
    color: var(--text-muted);
    cursor: pointer;
    transition: color $transition-fast, background $transition-fast;

    &:hover {
      color: var(--text-primary);
      background: rgba(255, 255, 255, 0.08);
    }
  }

  &__grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 6px;
  }

  &__tile {
    display: flex;
    align-items: center;
    gap: v.$spacing-sm;
    min-width: 0;
    padding: 6px 8px;
    border-radius: $border-radius-default; // 8
    background: rgba(255, 255, 255, 0.03);
    --smooth-border-color: #{rgba(255, 255, 255, 0.10)};
  }

  &__avatar {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: $border-radius-default;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.6875rem; // 11 — the floor
    font-weight: 700;
  }

  &__who {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }

  &__name {
    font-size: 0.8125rem; // 13
    font-weight: 500;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__sub {
    font-size: 0.75rem; // 12
    color: var(--text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  // Round by design — a status dot, the standing exception to the square rule.
  &__dot {
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }

  &__scope {
    display: flex;
    align-items: center;
    font-size: 0.75rem; // 12
    color: var(--text-muted);
  }
}
</style>
