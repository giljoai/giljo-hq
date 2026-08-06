<template>
  <div class="beat gj-anim">
    <div class="beat-eyebrow">01 · How it works</div>
    <h2 class="beat-title">Your tools do the thinking. Giljo HQ keeps the thread.</h2>
    <p class="beat-sub">
      Giljo HQ never runs AI. Your own coding tools ask it for context, and every answer starts them fully briefed.
      <router-link class="beat-readmore" :to="{ path: '/guide', hash: '#what-is-giljo-hq' }" target="_blank" rel="noopener">Read more →</router-link>
    </p>

    <div class="beat-stage">
      <div class="tools-col">
        <span class="col-label">YOUR AGENT INTERFACE</span>
        <div class="tool-chip"><v-icon size="18" class="tool-icon">mdi-console</v-icon><span class="tool-name">CLI</span></div>
        <div class="tool-chip"><v-icon size="18" class="tool-icon">mdi-web</v-icon><span class="tool-name">Web</span></div>
        <div class="tool-chip"><v-icon size="18" class="tool-icon">mdi-monitor</v-icon><span class="tool-name">Desktop app</span></div>
      </div>

      <div class="flow-lane">
        <span class="dot dot--req" style="top: 22px; animation-delay: 0s;" />
        <span class="dot dot--req" style="top: 62px; animation-delay: 0.7s;" />
        <span class="dot dot--req" style="top: 102px; animation-delay: 1.4s;" />
        <span class="dot dot--ctx" style="top: 42px; animation-delay: 1.1s;" />
        <span class="dot dot--ctx" style="top: 82px; animation-delay: 1.8s;" />
        <div class="lane-label lane-label--req">REQUESTS →</div>
        <div class="lane-label lane-label--ctx">← CONTEXT</div>
      </div>

      <div class="mcp-node">
        <img src="/icons/Giljo_YW_Face.svg" alt="" class="mcp-face" />
        <span class="mcp-name">{{ productName }}</span>
        <span class="mcp-tag">passive · always briefed</span>
      </div>
    </div>

    <div class="beat-footnote">
      Integrated with <span class="footnote-strong">Claude · ChatGPT/Codex · Gemini · Antigravity · OpenCode</span> — and any open MCP client.
      <template v-if="connectedToolNames">
        <br />you connected: {{ connectedToolNames }}
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useUserStore } from '@/stores/user'
import { PRODUCT_NAME } from '@/branding'

const productName = PRODUCT_NAME.toUpperCase()

// Live-state enhancement (approved): personalize from setup_selected_tools
// when available — appended under the interface cards, never replacing them.
const TOOL_NAMES = {
  claude_code: 'Claude Code CLI',
  codex_cli: 'Codex CLI',
  gemini_cli: 'Gemini CLI',
  antigravity_cli: 'Antigravity CLI',
}

const userStore = useUserStore()

const connectedToolNames = computed(() => {
  const ids = userStore.currentUser?.setup_selected_tools
  if (!Array.isArray(ids) || ids.length === 0) return ''
  return ids.map((id) => TOOL_NAMES[id] || id).join(', ')
})
</script>

<style scoped lang="scss">
@use '../../../styles/design-tokens' as *;

@keyframes gjDotFlow {
  0% { transform: translateX(0); opacity: 0; }
  15% { opacity: 1; }
  85% { opacity: 1; }
  100% { transform: translateX(150px); opacity: 0; }
}

@keyframes gjDotBack {
  0% { transform: translateX(0); opacity: 0; }
  15% { opacity: 1; }
  85% { opacity: 1; }
  100% { transform: translateX(-150px); opacity: 0; }
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
  gap: 0;
}

.tools-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.col-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  letter-spacing: 0.14em;
  color: var(--text-muted);
  text-align: center;
}

.tool-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  background: $elevation-raised;
  border-radius: $border-radius-md;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  padding: 12px 18px;
}

.tool-icon {
  color: $color-brand-yellow;
}

.tool-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12.5px;
  color: $color-text-primary;
}

.flow-lane {
  position: relative;
  width: 170px;
  height: 130px;
}

.dot {
  position: absolute;
  width: 8px;
  height: 8px;
  border-radius: $border-radius-pill;
}

.dot--req {
  left: 8px;
  background: $color-agent-implementor;
  animation: gjDotFlow 2.2s linear infinite;
}

.dot--ctx {
  right: 8px;
  background: $color-brand-yellow;
  animation: gjDotBack 2.2s linear infinite;
}

.lane-label {
  position: absolute;
  left: 0;
  right: 0;
  text-align: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  letter-spacing: 0.1em;
}

.lane-label--req {
  top: 50%;
  transform: translateY(-58px);
  color: $color-agent-implementor;
}

.lane-label--ctx {
  bottom: -6px;
  color: $color-brand-yellow;
}

.mcp-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  background: $elevation-raised;
  border-radius: 14px;
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.35);
  padding: 18px 22px;
}

.mcp-face {
  height: 34px;
}

.mcp-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: $color-text-primary;
}

.mcp-tag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  color: $color-agent-researcher;
}

.beat-footnote {
  text-align: center;
  padding-bottom: 8px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  line-height: 1.6;
  color: var(--text-muted);
}

.footnote-strong {
  color: var(--text-secondary);
}
</style>
