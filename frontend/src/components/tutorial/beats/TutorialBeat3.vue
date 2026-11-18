<template>
  <div class="beat gj-anim">
    <div class="beat-eyebrow">03 · Missions</div>
    <h2 class="beat-title">Missions, not monologues.</h2>
    <p class="beat-sub">
      Stage a project on the Jobs board; it becomes work orders your agents pick up. You watch it all there.
      <router-link class="beat-readmore" :to="{ path: '/guide', hash: '#projects' }" target="_blank" rel="noopener">Read more →</router-link>
    </p>

    <div class="beat-stage">
      <div class="jobs-card">
        <div class="jobs-header">
          <span class="jobs-title">JOBS · EXPORT MODULE MISSION</span>
          <span class="sample-pill">SAMPLE</span>
        </div>

        <div v-for="job in jobs" :key="job.task" class="job-row">
          <span class="job-badge" :style="{ background: job.tinted, color: job.hex }">{{ job.badge }}</span>
          <span class="job-task">{{ job.task }}</span>
          <span class="job-status">
            <span :class="['status-a', job.st1Class]">{{ job.st1 }}</span>
            <span :class="['status-b', job.st2Class]">{{ job.st2 }}</span>
          </span>
        </div>

        <div class="mission-row">
          <span class="mission-label">MISSION</span>
          <div class="mission-track">
            <div class="mission-fill" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { getAgentColor } from '@/config/agentColors'

function hexToTinted(hex) {
  const n = Number.parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, 0.15)`
}

function jobRow(role, task, st1, st1Class, st2, st2Class) {
  const color = getAgentColor(role)
  return { badge: color.badge, hex: color.hex, tinted: hexToTinted(color.hex), task, st1, st1Class, st2, st2Class }
}

const jobs = [
  jobRow('Implementer', 'Scaffold export endpoints', 'Working.', 'status--working', 'Complete.', 'status--complete'),
  jobRow('Tester', 'Regression sweep on auth', 'Waiting.', 'status--waiting', 'Working.', 'status--working'),
  jobRow('Documenter', 'Write change report', 'Queued.', 'status--queued', 'Waiting.', 'status--waiting'),
]
</script>

<style scoped lang="scss">
@use '../../../styles/design-tokens' as *;

@keyframes gjStatusA {
  0%, 45% { opacity: 1; }
  55%, 100% { opacity: 0; }
}

@keyframes gjStatusB {
  0%, 45% { opacity: 0; }
  55%, 100% { opacity: 1; }
}

@keyframes gjBarGrow {
  0% { width: 8%; }
  100% { width: 86%; }
}

.beat {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.beat-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.2em;
  color: $color-brand-yellow;
  text-transform: uppercase;
  margin-bottom: 10px;
}

.beat-title {
  margin: 0 0 6px;
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 28px;
  letter-spacing: -0.02em;
  color: $color-text-primary;
}

.beat-sub {
  margin: 0 0 8px;
  font-size: 14.5px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.beat-stage {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.jobs-card {
  width: 520px;
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  overflow: hidden;
}

.jobs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 16px;
  box-shadow: inset 0 -1px 0 rgba(255, 255, 255, 0.08);
}

.jobs-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--text-secondary);
}

.sample-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.05);
  padding: 3px 8px;
  border-radius: $border-radius-pill;
}

.job-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 12px 16px;
  box-shadow: inset 0 -1px 0 rgba(255, 255, 255, 0.05);
}

.job-badge {
  width: 26px;
  height: 26px;
  border-radius: $border-radius-default;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  font-weight: 700;
}

.job-task {
  flex: 1;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: $color-text-primary;
}

.job-status {
  position: relative;
  width: 86px;
  text-align: right;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10.5px;
  font-style: italic;
}

.status-a {
  position: absolute;
  right: 0;
  animation: gjStatusA 4s ease infinite;
}

.status-b {
  animation: gjStatusB 4s ease infinite;
}

.status--working { color: $color-status-working; }
.status--complete { color: $color-status-complete; }
.status--waiting { color: $color-status-waiting; }
.status--queued { color: $color-status-handed-over; }

.mission-row {
  padding: 11px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.mission-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  letter-spacing: 0.1em;
  color: var(--text-muted);
}

.mission-track {
  flex: 1;
  height: 6px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: $border-radius-pill;
  overflow: hidden;
}

.mission-fill {
  height: 100%;
  background: linear-gradient(90deg, $gradient-brand-end, $gradient-brand-start);
  border-radius: $border-radius-pill;
  animation: gjBarGrow 5s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
