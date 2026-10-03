<template>
  <div class="jb-drawer" data-testid="jb-drawer">
    <section class="jb-dsec" data-testid="jb-drawer-description">
      <div class="jb-dsec-k">
        <span>Project description</span>
        <span class="jb-sp" />
        <button
          type="button"
          class="jb-pen"
          title="Edit description"
          aria-label="Edit description"
          data-testid="jb-edit-description"
          @click="emit('edit-description', project)"
        >
          <v-icon size="13">mdi-pencil</v-icon>
        </button>
      </div>
      <p class="jb-dsec-t" :class="{ 'jb-dsec-t--empty': !project.description }">
        {{ project.description || 'No description yet.' }}
      </p>
    </section>

    <section class="jb-dsec" data-testid="jb-drawer-mission">
      <div class="jb-dsec-k">
        <span>Mission</span>
        <span v-if="missionState === 'written'" class="jb-otag" data-testid="jb-mission-tag">
          <v-icon size="11" aria-hidden="true">mdi-creation</v-icon>
          Orchestrator generated
        </span>
        <span v-else-if="missionState === 'writing'" class="jb-otag" data-testid="jb-mission-tag">
          <v-icon size="11" aria-hidden="true">mdi-creation</v-icon>
          Orchestrator writing<LiveDots />
        </span>
      </div>
      <p v-if="mission" class="jb-dsec-t jb-dsec-t--mono">{{ mission }}</p>
      <div v-else-if="missionState === 'writing'" class="jb-dsec-empty" data-testid="jb-mission-live">
        <span class="jb-dot jb-dot--writing" aria-hidden="true" />
        <span>Orchestrator is writing the mission in your harness.</span>
      </div>
      <div v-else class="jb-dsec-empty" data-testid="jb-mission-empty">
        <span class="jb-dot jb-dot--none" aria-hidden="true" />
        <span v-if="chainMember">Written when the chain reaches this step.</span>
        <span v-else>No mission yet. Press <b>Stage</b> and the orchestrator writes it.</span>
      </div>
    </section>

    <section class="jb-dsec" data-testid="jb-drawer-crew">
      <div class="jb-dsec-k"><span>Crew</span></div>
      <div v-if="agents.length" class="jb-crows">
        <div
          v-for="agent in agents"
          :key="agent.agent_id || agent.job_id || agent.id"
          class="jb-crow"
          data-testid="jb-crew-row"
        >
          <span
            class="agent-badge-sq jb-crow-badge"
            :class="{ 'live-badge': isLive(agent) }"
            :style="getAgentBadgeStyle(getAgentColorKey(agent))"
          >
            {{ getAgentInitials(getPrimaryAgentLabel(agent)) }}
          </span>
          <button
            type="button"
            class="jb-crow-n"
            data-testid="jb-crew-row-name"
            :aria-label="`About ${getPrimaryAgentLabel(agent)}`"
            @click="emit('agent-role', agent)"
          >
            {{ getPrimaryAgentLabel(agent) }}
            <small>{{ subLabel(agent) }}<LiveDots v-if="isLive(agent)" /></small>
          </button>
          <span class="jb-crow-ph">
            <template v-if="agent.phase != null">phase {{ agent.phase }}</template>
          </span>
          <button
            v-if="!launched && !isOrchestrator(agent)"
            type="button"
            class="jb-pen"
            :title="`Edit ${getPrimaryAgentLabel(agent)}'s mission`"
            :aria-label="`Edit ${getPrimaryAgentLabel(agent)}'s mission`"
            data-testid="jb-crew-edit"
            @click="emit('agent-mission-edit', agent)"
          >
            <v-icon size="13">mdi-pencil</v-icon>
          </button>
          <span v-else class="jb-pen-gap" />
        </div>
      </div>
      <p v-else class="jb-dsec-t jb-dsec-t--empty" data-testid="jb-crew-empty">
        <template v-if="chainMember">Chosen by the conductor when this step stages.</template>
        <template v-else>Workers are chosen when the mission is written.</template>
      </p>
    </section>
  </div>
</template>

<script setup>
import { getAgentBadgeStyle } from '@/utils/colorUtils'
import { getAgentColorKey, getAgentInitials } from '@/config/agentColors'
import { getPrimaryAgentLabel, getAgentRoleLabel, isOrchestrator } from '@/utils/agentDisplay'
import { jobStatusWord, jobStatusLabel, isLiveStatusWord } from '@/utils/jobStatusWord'
import LiveDots from './LiveDots.vue'

const props = defineProps({
  project: { type: Object, required: true },
  agents: { type: Array, default: () => [] },
  mission: { type: String, default: '' },
  missionState: { type: String, default: 'none' },
  launched: { type: Boolean, default: false },
  chainMember: { type: Boolean, default: false },
})

const emit = defineEmits(['edit-description', 'agent-role', 'agent-mission-edit'])

function isLive(agent) {
  return props.launched && isLiveStatusWord(jobStatusWord(agent))
}

function subLabel(agent) {
  if (props.launched) return jobStatusLabel(agent)
  if (isOrchestrator(agent)) return 'coordinates, mission not editable'
  return getAgentRoleLabel(agent) || 'agent'
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.jb-drawer {
  background: $elevation-elevated;
  border-radius: $border-radius-md;
  box-shadow: inset 0 0 0 1px $color-border-secondary;
  padding: 4px 16px;
  margin-bottom: 10px;
  min-width: 0;
}

.jb-dsec {
  padding: 12px 0;

  & + & {
    box-shadow: inset 0 1px 0 0 $color-border-tertiary;
  }
}

.jb-dsec-k {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: $color-text-secondary;
  margin-bottom: 6px;
}

.jb-sp {
  flex: 1;
}

.jb-dsec-t {
  font-size: 0.82rem;
  color: $color-text-tertiary;
  line-height: 1.6;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;

  &--mono {
    font-family: $typography-font-mono;
    font-size: 0.74rem;
    color: $color-text-primary;
  }

  &--empty {
    color: $color-text-secondary;
    font-size: 0.78rem;
  }
}

.jb-dsec-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.8rem;
  color: $color-text-secondary;

  b {
    color: $color-text-tertiary;
  }
}

.jb-otag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.62rem;
  font-weight: 600;
  text-transform: none;
  letter-spacing: 0;
  padding: 1px 8px;
  border-radius: $border-radius-pill;
  color: $color-agent-orchestrator;
  background: rgba($color-agent-orchestrator, 0.15);
}

.jb-dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;

  &--none {
    box-shadow: inset 0 0 0 1.5px $color-text-secondary;
  }

  &--writing {
    background: $color-status-waiting;
    animation: jb-pulse 1.4s ease-in-out infinite;
  }
}

@keyframes jb-pulse {
  50% {
    opacity: 0.35;
  }
}

@media (prefers-reduced-motion: reduce) {
  .jb-dot--writing {
    animation: none;
  }
}

.jb-pen {
  flex: none;
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: $border-radius-sharp;
  background: none;
  border: 0;
  padding: 0;
  color: $color-text-tertiary;
  cursor: pointer;

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
    background: rgba($color-brand-yellow, 0.08);
  }
}

.jb-pen-gap {
  width: 24px;
}

.jb-crows {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.jb-crow {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 5px 4px 5px 6px;
  border-radius: $border-radius-default;
  min-width: 0;

  &:hover {
    background: rgba(255, 255, 255, 0.04);
  }
}

.jb-crow-badge {
  width: 28px;
  height: 28px;
  font-size: 0.58rem;
  border-radius: 6px;
}

.jb-crow-n {
  min-width: 0;
  text-align: left;
  background: none;
  border: 0;
  padding: 0;
  font: inherit;
  font-size: 0.82rem;
  color: $color-text-primary;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;

  small {
    color: $color-text-secondary;
    font-size: 0.72rem;
    margin-left: 6px;
  }

  &:hover,
  &:focus-visible {
    color: $color-brand-yellow;
  }
}

.jb-crow-ph {
  font-family: $typography-font-mono;
  font-size: 0.65rem;
  color: $color-text-secondary;
  white-space: nowrap;
}
</style>
