<template>
  <div class="step-commands">
    <p class="step-heading-grad">Install skills</p>
    <p class="step-sub">One command installs the <span class="inline-code">/giljo</span> skill and writes the Giljo HQ marker block. Agents receive their profile from the server when a job starts.</p>

    <div v-if="tools.length > 1" class="tool-tabs" role="tablist">
      <button
        v-for="tool in tools"
        :key="tool.id"
        role="tab"
        :aria-selected="activeToolId === tool.id"
        :class="['tool-tab', 'smooth-border', { 'tool-tab--active': activeToolId === tool.id }]"
        @click="activeToolId = tool.id"
      >
        <img v-if="tool.logo" :src="tool.logo" :alt="tool.name" class="tool-tab-logo" />
        <v-icon v-else size="18" class="tool-tab-logo">{{ tool.icon }}</v-icon>
        <span>{{ tool.name }}</span>
      </button>
    </div>

    <div class="wiz-center">
      <div class="tool-panel" role="tabpanel">

        <div class="panel-section">
          <div class="install-cmd-card">
            <div class="install-cmd-head">
              <span class="install-cmd-step">1.</span>
              <span class="install-cmd-label">Ask your {{ activeTool.name }} to run:</span>
            </div>
            <div class="install-cmd-code">giljo_setup</div>
          </div>
          <p class="instruction-hint">
            This installs the skills and the marker block. Run it again whenever the skills are outdated.
          </p>
        </div>

        <div class="checklist-centered">
          <div class="checklist-column">
          <div class="checklist-item">
            <v-icon
              size="20"
              data-testid="setup-skills-dot"
              :color="toolStatus[activeToolId]?.commands ? COLOR_SUCCESS : COLOR_MUTED"
            >
              {{ toolStatus[activeToolId]?.commands ? 'mdi-check-circle' : 'mdi-checkbox-blank-circle-outline' }}
            </v-icon>
            <span :class="['checklist-text', { 'checklist-text--done': toolStatus[activeToolId]?.commands }]">
              Skills downloaded
            </span>
          </div>

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
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { useWebSocketStore } from '@/stores/websocket'
import { TEXT_MUTED_BLUE as COLOR_MUTED, COLOR_SUCCESS_SETUP as COLOR_SUCCESS } from '@/config/colorTokens'
import { TOOL_META } from '@/config/setupTools'

const props = defineProps({
  connectedTools: {
    type: Array,
    required: true,
  },
})

const emit = defineEmits(['can-proceed', 'step-data'])

const wsStore = useWebSocketStore()

const tools = computed(() =>
  props.connectedTools.map((id) => ({
    id,
    ...TOOL_META[id],
  })),
)

const activeTool = computed(() => TOOL_META[activeToolId.value] || { name: 'Tool' })

const activeToolId = ref(props.connectedTools[0] || 'claude_code')

const toolStatus = reactive({})
watch(
  () => props.connectedTools,
  (ids) => {
    for (const id of ids) {
      if (!toolStatus[id]) {
        toolStatus[id] = { commands: false }
      }
    }
    if (ids.length > 0 && !ids.includes(activeToolId.value)) {
      activeToolId.value = ids[0]
    }
  },
  { immediate: true },
)

function isToolComplete(toolId) {
  return !!toolStatus[toolId]?.commands
}

const canProceed = computed(() =>
  props.connectedTools.some((id) => isToolComplete(id)) || isToolComplete(activeToolId.value),
)

const installedTools = computed(() =>
  props.connectedTools.filter((id) => isToolComplete(id)),
)

watch(canProceed, (val) => {
  emit('can-proceed', val)
}, { immediate: true })

watch(installedTools, (val) => {
  emit('step-data', { installedTools: [...val] })
}, { deep: true })

let unsubCommands = null

function handleCommandsInstalled(payload) {
  const toolName = payload?.tool_name
  if (!toolName) return

  if (toolName === 'all') {
    for (const id of props.connectedTools) {
      if (toolStatus[id]) toolStatus[id].commands = true
    }
    return
  }

  if (toolStatus[toolName]) {
    toolStatus[toolName].commands = true
  }
}

function handleBootstrapComplete() {
  for (const id of props.connectedTools) {
    if (toolStatus[id]) toolStatus[id].commands = true
  }
}

let unsubBootstrap = null

onMounted(() => {
  unsubCommands = wsStore.on('setup:commands_installed', handleCommandsInstalled)
  unsubBootstrap = wsStore.on('setup:bootstrap_complete', handleBootstrapComplete)
})

onUnmounted(() => {
  if (unsubCommands) unsubCommands()
  if (unsubBootstrap) unsubBootstrap()
})
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;
@use '../../styles/setup-wizard-shared' as wiz;

@include wiz.setup-step-heading;
@include wiz.setup-tool-tabs;
@include wiz.setup-panel-section;
@include wiz.setup-wiz-center;

.step-commands {
  max-width: 680px;
  margin: 0 auto;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.step-sub {
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.88rem;
  margin: 0 auto 4px;
  max-width: 40rem;
}

.tool-tab:focus-visible {
  outline: 2px solid $color-brand-yellow;
  outline-offset: 2px;
}

.tab-status-dot--complete {
  background: $gradient-brand-end;
}

.section-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 500;
  color: $color-text-primary;
  margin-bottom: 10px;
}

/* Instruction text */
.instruction-text {
  font-size: 0.875rem;
  color: $color-text-primary;
  margin-bottom: 12px;
  text-align: center;
}

.inline-code {
  font-family: "Roboto Mono", "Courier New", monospace;
  font-size: 0.8125rem;
  background: rgba($color-brand-yellow, 0.1);
  color: $color-brand-yellow;
  padding: 2px 6px;
  border-radius: $border-radius-sharp;
}

/* giljo_setup command — numbered command card (matches the connect step idiom). */
.install-cmd-card {
  background: $elevation-elevated;
  border-radius: $border-radius-md;
  padding: 16px 18px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.10);
  margin-bottom: 12px;
}

.install-cmd-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.install-cmd-step {
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
  font-size: 0.94rem;
  color: $color-brand-yellow;
}

.install-cmd-label {
  font-size: 0.84rem;
  color: $color-text-primary;
}

.install-cmd-code {
  background: $color-background-primary;
  border-radius: $border-radius-default;
  padding: 11px 14px;
  font-family: "Roboto Mono", "Courier New", monospace;
  font-size: 0.9rem;
  font-weight: 600;
  color: $color-brand-yellow;
}

.instruction-hint {
  font-size: 0.8125rem;
  color: $lightest-blue;
  text-align: center;
  margin-bottom: 16px;
}

/* Manual setup hint */
.manual-setup-hint {
  font-size: 0.8125rem;
  color: $lightest-blue;
  text-align: center;
  margin-top: 20px;
}

/* Checklist items */
.checklist-centered {
  display: flex;
  justify-content: center;
  margin-bottom: 8px;
}

.checklist-column {
  display: flex;
  flex-direction: column;
}

.checklist-item {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.checklist-text {
  font-size: 0.875rem;
  color: $lightest-blue;
  transition: color 250ms ease-out;
}

.checklist-text--done {
  color: $gradient-brand-end;
}

/* Tip text */
.tip-text {
  font-size: 0.8125rem;
  color: $lightest-blue;
  margin-top: 8px;
  line-height: 1.5;
  font-style: italic;
}

/* Transition for post-install command */
.fade-slide-enter-active {
  transition: opacity 250ms ease-out, transform 250ms ease-out;
}

.fade-slide-leave-active {
  transition: opacity 200ms ease-in, transform 200ms ease-in;
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(-8px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
