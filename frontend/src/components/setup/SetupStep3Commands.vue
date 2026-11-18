<template>
  <div class="step-commands">
    <p class="step-heading-grad">Setup instructions</p>
    <p class="step-sub">
      One request installs the <span class="inline-code">/giljo</span> skill and writes the Giljo HQ
      marker block in your tool.
    </p>

    <div v-if="tools.length > 1" class="tool-tabs" role="tablist">
      <button
        v-for="tool in tools"
        :key="tool.id"
        type="button"
        role="tab"
        :aria-selected="activeToolId === tool.id"
        :data-testid="`setup-tab-${tool.id}`"
        :class="['tool-tab', 'smooth-border', { 'tool-tab--active': activeToolId === tool.id }]"
        @click="activeToolId = tool.id"
      >
        <img v-if="tool.logo" :src="tool.logo" :alt="tool.name" class="tool-tab-logo" />
        <span>{{ tool.name }}</span>
      </button>
    </div>

    <div class="wiz-center">
      <div class="tool-panel" role="tabpanel">
        <div class="install-cmd-card">
          <div class="install-cmd-head">
            <span class="install-cmd-label" data-testid="setup-ask-line">{{ askLine }}</span>
          </div>
          <div class="install-cmd-code">giljo_setup</div>
          <button
            type="button"
            :class="['copy-request', 'smooth-border', { 'copy-request--copied': copied }]"
            data-testid="setup-copy-request"
            @click="copyRequest"
          >
            <v-icon v-if="copied" size="14" icon="mdi-check" />
            {{ copied ? GUIDE_TEXT.copied : 'Copy the request' }}
          </button>
        </div>
        <p class="instruction-hint">Run it again whenever the skills are outdated.</p>

        <div class="checklist-centered">
          <div class="checklist-item">
            <v-icon
              size="20"
              data-testid="setup-skills-dot"
              :data-done="String(skillsDone)"
              :color="skillsDone ? COLOR_SUCCESS : COLOR_MUTED"
            >
              {{ skillsDone ? 'mdi-check-circle' : 'mdi-checkbox-blank-circle-outline' }}
            </v-icon>
            <span :class="['checklist-text', { 'checklist-text--done': skillsDone }]">Skills downloaded</span>
          </div>
        </div>

        <p class="manual-setup-hint">
          For manual setup, go to <strong>Tools &gt; Connect</strong>
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

import { TEXT_MUTED_BLUE as COLOR_MUTED, COLOR_SUCCESS_SETUP as COLOR_SUCCESS } from '@/config/colorTokens'
import { TOOL_META } from '@/config/setupTools'
import { GUIDE_TEXT } from '@/content/onboarding/guide'
import { useSetupRequestCopy } from '@/composables/useSetupRequestCopy'
import { useStartListStore } from '@/stores/startList'

const props = defineProps({
  tools: { type: Array, default: () => [] },
})

const list = useStartListStore()
const { copied, copyRequest } = useSetupRequestCopy()

const tools = computed(() => props.tools.filter((id) => TOOL_META[id]).map((id) => TOOL_META[id]))

const activeToolId = ref(tools.value[0]?.id ?? null)
watch(tools, (all) => {
  if (!all.some((t) => t.id === activeToolId.value)) activeToolId.value = all[0]?.id ?? null
})

const askLine = computed(() => {
  const name = TOOL_META[activeToolId.value]?.name ?? 'AI tool'
  return `Ask your ${name} to run giljo_setup.`
})

const skillsDone = computed(() => list.rows?.skills_installed?.done === true)
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;
@use '../../styles/setup-wizard-shared' as wiz;

@include wiz.setup-wiz-center;

.step-commands {
  max-width: 680px;
  margin: 0 auto;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.step-heading-grad {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 1.2rem;
  text-align: center;
  margin: 4px 0 4px;
  letter-spacing: -0.01em;
  background: var(--gradient-brand);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.step-sub {
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.88rem;
  margin: 0 auto 16px;
  max-width: 40rem;
}

.tool-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-bottom: 16px;
}

.tool-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: $elevation-elevated;
  border: none;
  border-radius: $border-radius-default;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.8125rem;
  font-weight: 500;
  transition: color 250ms ease-out, box-shadow 250ms ease-out;
}

.tool-tab--active {
  color: $color-brand-yellow;
  --smooth-border-color: #{$color-brand-yellow};
}

.tool-tab:hover:not(.tool-tab--active) {
  color: $color-text-primary;
}

.tool-tab:focus-visible,
.copy-request:focus-visible {
  outline: 2px solid $color-brand-yellow;
  outline-offset: 2px;
}

.tool-tab-logo {
  width: 20px;
  height: 20px;
  object-fit: contain;
}

.inline-code {
  font-family: 'Roboto Mono', 'Courier New', monospace;
  font-size: 0.8125rem;
  background: rgba($color-brand-yellow, 0.1);
  color: $color-brand-yellow;
  padding: 2px 6px;
  border-radius: $border-radius-sharp;
}

.install-cmd-card {
  background: $elevation-elevated;
  border-radius: $border-radius-md;
  padding: 16px 18px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  margin-bottom: 12px;
}

.install-cmd-head {
  margin-bottom: 10px;
}

.install-cmd-label {
  font-size: 0.9rem;
  color: $color-text-primary;
}

.install-cmd-code {
  background: $color-background-primary;
  border-radius: $border-radius-default;
  padding: 11px 14px;
  font-family: 'Roboto Mono', 'Courier New', monospace;
  font-size: 0.9rem;
  font-weight: 600;
  color: $color-brand-yellow;
}

.copy-request {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 7px 14px;
  border: none;
  border-radius: $border-radius-default;
  background: transparent;
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  transition: color 150ms ease-out;
}

.copy-request:hover {
  color: $color-brand-yellow;
}

.copy-request--copied {
  color: $color-brand-yellow;
  --smooth-border-color: #{$color-brand-yellow};
}

.instruction-hint {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  text-align: center;
  margin-bottom: 16px;
}

.manual-setup-hint {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  text-align: center;
  margin-top: 20px;
}

.checklist-centered {
  display: flex;
  justify-content: center;
  margin-bottom: 8px;
}

.checklist-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.checklist-text {
  font-size: 0.875rem;
  color: var(--text-secondary);
  transition: color 250ms ease-out;
}

.checklist-text--done {
  color: $gradient-brand-end;
}
</style>
