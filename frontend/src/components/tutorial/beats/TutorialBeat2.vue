<template>
  <div class="beat gj-anim">
    <div class="beat-eyebrow">02 · Your product &amp; crew</div>
    <h2 class="beat-title">Define your product once. Brief the whole crew.</h2>
    <p class="beat-sub">
      Stack, architecture, vision. Every agent template starts from the same brief.
      <router-link class="beat-readmore" :to="{ path: '/guide', hash: '#products' }" target="_blank" rel="noopener">Read more →</router-link>
    </p>

    <div class="beat-stage">
      <div class="product-col">
        <span class="col-heading">My Product</span>
        <div class="product-card">
          <div class="chip-row">
            <span class="chip chip--tech" style="animation-delay: 0.2s;">Vue 3</span>
            <span class="chip chip--tech" style="animation-delay: 0.45s;">FastAPI</span>
            <span class="chip chip--tech" style="animation-delay: 0.7s;">PostgreSQL</span>
            <span class="chip chip--vision" style="animation-delay: 0.95s;">Vision doc</span>
            <span class="chip chip--vision" style="animation-delay: 1.2s;">Architecture</span>
          </div>
          <div class="terminal-strip">
            <span class="terminal-cmd">/giljo</span>
            <span class="terminal-cursor" />
            <span class="terminal-status">skills loaded ✓</span>
          </div>
        </div>
        <span class="col-footnote">Tune what agents see in <span class="footnote-noun">Context&nbsp;Configurator</span>.</span>
      </div>

      <div class="crew-col">
        <span class="col-heading">My agents</span>
        <div class="crew-grid">
          <div
            v-for="(member, i) in crew"
            :key="member.name"
            class="crew-card"
            :style="{ animationDelay: `${0.3 + i * 0.35}s` }"
          >
            <span
              class="crew-badge"
              :style="{ background: member.tinted, color: member.hex }"
            >{{ member.badge }}</span>
            <span class="crew-name">{{ member.name }}</span>
          </div>
        </div>
        <span class="col-footnote">Add, remove, and customize your crew in <span class="footnote-noun">Agent&nbsp;Manager</span>.</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { getAgentColor } from '@/config/agentColors'

const CREW_ROLES = ['Orchestrator', 'Analyzer', 'Implementer', 'Documenter', 'Reviewer', 'Tester']

function hexToTinted(hex) {
  const n = Number.parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, 0.15)`
}

const crew = CREW_ROLES.map((name) => {
  const color = getAgentColor(name)
  return { name, badge: color.badge, hex: color.hex, tinted: hexToTinted(color.hex) }
})
</script>

<style scoped lang="scss">
@use '../../../styles/design-tokens' as *;

@keyframes gjChipIn {
  0% { opacity: 0; transform: translateY(10px) scale(0.95); }
  100% { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes gjGlowUp {
  0%, 100% { box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1); }
  50% { box-shadow: inset 0 0 0 1px rgba(255, 195, 0, 0.5); }
}

@keyframes gjType {
  0% { width: 0; }
  100% { width: 6ch; }
}

@keyframes gjBlinkCursor {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
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
  gap: 40px;
}

.product-col {
  width: 300px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.crew-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.col-heading {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 15px;
  color: $color-text-primary;
}

.product-card {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.chip {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10.5px;
  padding: 5px 10px;
  border-radius: $border-radius-pill;
  animation: gjChipIn 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.chip--tech {
  color: $color-agent-implementor;
  background: rgba($color-agent-implementor, 0.12);
}

.chip--vision {
  color: $color-agent-researcher;
  background: rgba($color-agent-researcher, 0.12);
}

.terminal-strip {
  background: $color-background-primary;
  border-radius: $border-radius-default;
  padding: 9px 12px;
  display: flex;
  align-items: center;
  gap: 2px;
  margin-top: 4px;
}

.terminal-cmd {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: $color-brand-yellow;
  overflow: hidden;
  white-space: nowrap;
  display: inline-block;
  animation: gjType 1.2s steps(6) 1.6s both;
}

.terminal-cursor {
  width: 7px;
  height: 14px;
  background: $color-text-primary;
  animation: gjBlinkCursor 1s step-end infinite;
}

.terminal-status {
  margin-left: auto;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  color: $color-agent-researcher;
  animation: gjChipIn 0.4s ease 2.9s both;
}

.crew-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.crew-card {
  display: flex;
  align-items: center;
  gap: 9px;
  background: $elevation-raised;
  border-radius: 10px;
  padding: 9px 13px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  animation: gjGlowUp 2.6s ease infinite;
}

.crew-badge {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  font-weight: 700;
}

.crew-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11.5px;
  color: $color-text-primary;
}

/* Walkthrough fix 2 (owner direction, overrides the mock's 9.5px spec):
   two sizes up and brighter — these name the two follow-up destinations. */
.col-footnote {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: $color-text-primary;
}

.footnote-noun {
  white-space: nowrap;
}
</style>
