<template>
  <div class="team-section">
    <div class="team-header">
      <div class="section-label mb-0">Your Team</div>
      <div class="d-flex align-center ga-2">
        <v-tooltip v-if="hasStaleAgents" location="bottom" max-width="300">
          <template #activator="{ props }">
            <span v-bind="props" class="stale-agents-warning">
              <v-icon size="14">mdi-alert</v-icon> Re-export agents
            </span>
          </template>
          <span>Agent templates have changed since your last export. Run the <code>giljo_setup</code> tool (choose "Agents only") to update your local agent files.</span>
        </v-tooltip>
        <span class="team-slots smooth-border">{{ activeTemplates.length + 1 }} / {{ totalSlots }} slots</span>
        <router-link to="/settings?tab=agents" class="team-manage">
          <v-icon size="14">mdi-cog</v-icon> Manage
        </router-link>
      </div>
    </div>
    <div class="team-grid">
      <!-- Orchestrator: system agent, always present -->
      <div class="team-card smooth-border">
        <div class="team-avatar-wrap">
          <div
            class="team-avatar"
            :style="{
              background: tintedBg(orchestratorColor.hex),
              color: orchestratorColor.hex,
            }"
          >
            OR
          </div>
        </div>
        <div class="team-name">orchestrator</div>
        <div class="team-desc">Primary coordinator and mission planner</div>
      </div>
      <div
        v-for="tmpl in activeTemplates"
        :key="tmpl.id"
        class="team-card smooth-border"
      >
        <div class="team-avatar-wrap">
          <div
            class="team-avatar"
            :style="{
              background: tintedBg(tmpl.color),
              color: tmpl.color,
            }"
          >
            {{ tmpl.badge }}
          </div>
        </div>
        <div class="team-name">{{ tmpl.name }}</div>
        <div class="team-desc">{{ tmpl.description }}</div>
      </div>
      <div
        v-for="n in emptySlots"
        :key="'empty-' + n"
        class="team-card empty-slot"
      >
        <div class="team-avatar-wrap">
          <div class="team-avatar empty-avatar">
            <v-icon size="16">mdi-plus</v-icon>
          </div>
        </div>
        <div class="team-name" style="color:var(--text-muted);">Empty Slot</div>
        <div class="team-desc">Add an agent</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { getAgentColor } from '@/config/agentColors'

defineProps({
  activeTemplates: {
    type: Array,
    required: true,
  },
  emptySlots: {
    type: Number,
    default: 0,
  },
  totalSlots: {
    type: Number,
    default: 8,
  },
  hasStaleAgents: {
    type: Boolean,
    default: false,
  },
})

const orchestratorColor = getAgentColor('orchestrator')

function tintedBg(hex) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},0.15)`
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

/* ═══ SECTION LABEL ═══ */
.section-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin-bottom: 12px;
  font-weight: 500;
}

/* ═══ YOUR TEAM ═══ */
.team-section {
  margin-bottom: 36px;
  animation: fadeSlideUp 0.45s ease-out 0.35s both;
}

.team-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.stale-agents-warning {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.72rem;
  font-weight: 500;
  color: var(--agent-tester-primary);
  cursor: help;
}

.team-slots {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: var(--text-muted);
  padding: 2px 8px;
  border-radius: $border-radius-pill;
}

.team-manage {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  color: $yellow;
  cursor: pointer;
  opacity: 0.7;
  transition: opacity $transition-normal;
  text-decoration: none;
}

.team-manage:hover {
  opacity: 1;
}

.team-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

.team-card {
  background: rgb(var(--v-theme-surface));
  border-radius: $border-radius-rounded;
  padding: 16px 14px 20px;
  cursor: pointer;
  transition: all $transition-normal;
  text-align: center;
}

.team-card:hover {
  transform: translateY(-2px);
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255,255,255,0.10)), 0 6px 16px -4px rgba(0,0,0,0.25);
}

.team-avatar-wrap {
  width: 44px;
  margin: 0 auto 8px;
}

.team-avatar {
  width: 44px;
  height: 44px;
  border-radius: $border-radius-md;
  display: grid;
  place-items: center;
  font-size: 0.78rem;
  font-weight: 700;
  transition: box-shadow $transition-normal;
}

.empty-avatar {
  background: rgba(255,255,255,0.05);
  color: var(--text-muted);
}

.team-name {
  font-size: 0.75rem;
  font-weight: 500;
  margin-bottom: 2px;
}

.team-desc {
  font-size: 0.62rem;
  color: var(--text-muted);
  line-height: 1.3;
}

.team-card.empty-slot {
  border: 1px dashed rgba(255,255,255,0.1);
  box-shadow: none;
  background: transparent;
  opacity: 0.4;
}

.team-card.empty-slot:hover {
  opacity: 0.6;
  transform: none;
  box-shadow: none;
}

/* Keyframe used by team-section animation */
@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ═══ RESPONSIVE ═══ */
@media (max-width: 960px) {
  .team-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
