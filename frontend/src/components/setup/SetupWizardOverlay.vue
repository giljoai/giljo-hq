<template>
  <Teleport to="body">
    <Transition name="overlay-fade">
      <div
        v-if="modelValue"
        class="setup-wizard-overlay"
        data-testid="setup-wizard-overlay"
        role="dialog"
        aria-modal="true"
        :aria-label="setupAriaLabel"
        @keydown.escape="handleDismiss"
      >
        <!-- Backdrop — click does NOT close -->
        <div class="setup-wizard-backdrop" />

        <!-- ============================================================
             SETUP MODE — Gradient Rail (FE-6259b).
             Left: vertical gradient stepper. Right: step content + footer.
             (Learning mode was replaced by the onboarding tutorial —
             frontend/src/components/tutorial/TutorialOverlay.vue, FE-9200.)
             ============================================================ -->
        <div class="wizard-rail-panel smooth-border" tabindex="-1">
          <v-btn
            icon
            variant="text"
            size="small"
            class="wizard-rail-close-btn"
            aria-label="Close setup wizard"
            @click="handleDismiss"
          >
            <v-icon>mdi-close</v-icon>
          </v-btn>

          <!-- Closing state: all checkmarks, brief confirmation (replaces the whole body) -->
          <div v-if="closingWithCheckmarks" class="closing-confirmation">
            <v-icon size="48" color="success" class="closing-icon">mdi-check-circle</v-icon>
            <div class="closing-text">Setup complete</div>
          </div>

          <template v-else>
            <!-- Left rail: gradient stepper -->
            <aside class="wizard-rail">
              <div class="rail-top">
                <img src="/icons/Giljo_YW_Face.svg" alt="" class="rail-logo" />
                <div>
                  <div class="rail-title">Set up GiljoAI</div>
                  <div class="rail-count">Step {{ Math.min(currentStep, 3) + 1 }} of 4</div>
                </div>
              </div>

              <div class="stepper">
                <div class="spine">
                  <div class="spine-fill" :style="{ height: spineFillPct + '%' }" />
                </div>
                <template v-for="(step, i) in STEPS" :key="step.id">
                  <div
                    :style="{ '--nodecol': STEP_COLORS[i] }"
                    :class="[
                      'rail-node',
                      {
                        'rail-node--done': i < currentStep,
                        'rail-node--active': i === currentStep,
                        'rail-node--clickable': i < currentStep,
                      },
                    ]"
                    :data-testid="`rail-node-${step.id}`"
                    role="button"
                    :tabindex="i < currentStep ? 0 : -1"
                    :aria-current="i === currentStep ? 'step' : undefined"
                    @click="goToStep(i)"
                    @keydown.enter.prevent="goToStep(i)"
                    @keydown.space.prevent="goToStep(i)"
                  >
                    <span class="rail-dot">
                      <v-icon v-if="i < currentStep" size="13">mdi-check</v-icon>
                      <template v-else>{{ i + 1 }}</template>
                    </span>
                    <span class="rail-txt">
                      <span class="rail-node-label">{{ step.label }}</span>
                      <span class="rail-node-desc">{{ STEP_DESC[i] }}</span>
                    </span>
                  </div>

                  <!-- Connect stage: per-tool sub-rows (green done / amber pulse current /
                       blank ahead). State comes from wizard progression, never event attribution. -->
                  <div
                    v-if="step.id === 'connect' && currentStep === 1 && connectSubRows.length"
                    class="rail-subs"
                  >
                    <div
                      v-for="sub in connectSubRows"
                      :key="sub.id"
                      class="rail-sub"
                      :data-testid="`rail-sub-${sub.id}`"
                    >
                      <span :class="['rail-sub-dot', `rail-sub-dot--${sub.state}`]" />
                      <span class="rail-sub-label">{{ sub.name }}</span>
                      <span class="rail-sub-status">{{ sub.statusText }}</span>
                    </div>
                  </div>
                </template>
              </div>
            </aside>

            <!-- Right: step content + footer -->
            <main class="wizard-main">
              <div class="wizard-content" data-testid="wizard-content">
                <!-- Step 0: Choose Tools -->
                <div v-if="currentStep === 0" class="step-tools">
                  <p class="step-heading-grad">Choose your tools</p>
                  <p class="step-sub">
                    Which AI coding agent(s) do you use? Pick one or more. You can add the rest later.
                  </p>

                  <div class="wiz-center">
                    <div class="tools-grid tools-grid--six">
                      <div
                        v-for="tool in SETUP_TOOLS"
                        :key="tool.id"
                        :class="['tool-card', 'tool-card--row', 'smooth-border', { 'tool-card--sel': isSelected(tool.id) }]"
                        :data-testid="`tool-select-${tool.id}`"
                        role="checkbox"
                        :aria-checked="isSelected(tool.id)"
                        :aria-label="tool.name"
                        tabindex="0"
                        @click="toggleTool(tool.id)"
                        @keydown.enter.prevent="toggleTool(tool.id)"
                        @keydown.space.prevent="toggleTool(tool.id)"
                      >
                        <span class="tool-card-well">
                          <img v-if="tool.logo" :src="tool.logo" :alt="tool.name" class="tool-card-logo" />
                          <v-icon v-else size="22">{{ tool.icon }}</v-icon>
                        </span>
                        <span class="tool-card-text">
                          <span class="tool-name">{{ tool.name }}</span>
                          <span class="tool-method" :data-testid="`tool-method-${tool.id}`">{{ toolMethodTag(tool.id) }}</span>
                        </span>
                        <span v-if="isSelected(tool.id)" class="tool-card-ring tool-card-ring--on"><v-icon size="12">mdi-check-bold</v-icon></span>
                        <span v-else class="tool-card-ring" />
                      </div>
                    </div>
                    <p class="step-fineprint">
                      The named tools get a one-command setup. Generic MCP client covers anything else that
                      speaks open MCP. Add more later in Tools &gt; Connect.
                    </p>
                  </div>
                </div>

                <!-- Step 1: Connect — walk one tool at a time (FE-9204) -->
                <SetupStep2Connect
                  v-else-if="currentStep === 1"
                  :selected-tools="localSelectedTools"
                  @can-proceed="step2CanProceed = $event"
                  @step-data="step2Data = $event"
                  @walk-state="step2WalkState = $event"
                  @advance-step="handleNext"
                />

                <!-- Step 2: Install (0855e) -->
                <SetupStep3Commands
                  v-else-if="currentStep === 2"
                  :selected-tools="localSelectedTools"
                  :connected-tools="step2ConnectedTools"
                  @can-proceed="step3CanProceed = $event"
                  @step-data="step3Data = $event"
                />

                <!-- Step 3: Launch (0855f) -->
                <SetupStep4Complete v-else-if="currentStep === 3" />
              </div>

              <div class="wz-footer">
                <div class="footer-row">
                  <v-btn
                    v-if="currentStep > 0"
                    variant="text"
                    class="footer-back"
                    @click="handleBack"
                  >
                    Back
                  </v-btn>
                  <span class="footer-spacer" />

                  <template v-if="currentStep === 3">
                    <v-btn
                      v-if="props.isRerun"
                      variant="text"
                      prepend-icon="mdi-restart"
                      class="footer-restart"
                      data-testid="setup-restart-btn"
                      @click="showRestartConfirm = true"
                    >
                      Restart setup
                    </v-btn>
                    <v-btn
                      color="primary"
                      variant="flat"
                      class="footer-next-btn"
                      data-testid="setup-finish-btn"
                      @click="handleFinish"
                    >
                      {{ props.isRerun ? 'Done' : 'Finish' }}
                    </v-btn>
                  </template>
                  <template v-else>
                    <v-btn
                      color="primary"
                      variant="flat"
                      class="footer-next-btn"
                      data-testid="setup-next-btn"
                      :disabled="!canProceed"
                      @click="handleNext"
                    >
                      Next
                    </v-btn>
                  </template>
                </div>

                <div v-if="footerSkipLabel" class="footer-skip">
                  <button
                    type="button"
                    class="skiplink"
                    :data-testid="footerSkipTestId"
                    @click="handleFooterSkip"
                  >
                    {{ footerSkipLabel }}
                  </button>
                </div>
              </div>
            </main>
          </template>
        </div>
      </div>
    </Transition>

    <!-- Restart confirmation dialog -->
    <v-dialog v-model="showRestartConfirm" max-width="380">
      <v-card class="smooth-border">
        <div class="dlg-header dlg-header--warning">
          <v-icon class="dlg-icon">mdi-alert</v-icon>
          <span class="dlg-title">Restart Setup</span>
          <v-btn icon variant="text" size="small" class="dlg-close" @click="showRestartConfirm = false">
            <v-icon icon="mdi-close" size="18" />
          </v-btn>
        </div>
        <v-card-text class="pa-4">
          Setup is already completed. Are you sure you want to restart?
        </v-card-text>
        <div class="dlg-footer">
          <v-spacer />
          <v-btn variant="text" @click="showRestartConfirm = false">Cancel</v-btn>
          <v-btn variant="flat" color="warning" @click="handleRestartConfirmed">Yes</v-btn>
        </div>
      </v-card>
    </v-dialog>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import configService from '@/services/configService'
import { SETUP_TOOLS, methodTag, toolName } from '@/config/setupTools'
import { useConnectedToolsResumeSeed } from '@/composables/useConnectedToolsResumeSeed'
import { PRODUCT_NAME } from '@/branding'
import SetupStep2Connect from './SetupStep2Connect.vue'
import SetupStep3Commands from './SetupStep3Commands.vue'
import SetupStep4Complete from './SetupStep4Complete.vue'

const setupAriaLabel = `Setup ${PRODUCT_NAME}`

const STEPS = [
  { id: 'tools', label: 'Choose Tools' },
  { id: 'connect', label: 'Connect' },
  { id: 'install', label: 'Install' },
  { id: 'launch', label: 'Launch' },
]

// Rail node descriptions (Gradient Rail pixel spec). One per STEPS entry.
const STEP_DESC = ['Pick your AI agents', 'Attach them to GiljoAI', 'Skills & agent templates', "You're ready"]

// Node colors sampled along the brand gradient (design-tokens.scss / main.scss).
const STEP_COLORS = ['var(--gradient-step-1)', 'var(--gradient-step-2)', 'var(--gradient-step-3)', 'var(--gradient-step-4)']

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
  currentStep: {
    type: Number,
    default: 0,
  },
  selectedTools: {
    type: Array,
    default: () => [],
  },
  isRerun: {
    type: Boolean,
    default: false,
  },
  mode: {
    type: String,
    default: 'setup',
  },
})

const emit = defineEmits([
  'update:modelValue',
  'update:currentStep',
  'dismiss',
  'step-complete',
])

// Internal state
const localSelectedTools = ref([...props.selectedTools])
const step2CanProceed = ref(false)
const step2Data = ref({})
const step2WalkState = ref(null)
const step3CanProceed = ref(false)
const step3Data = ref({})
const showRestartConfirm = ref(false)

// Edition drives the choose-grid method tags (CE = every tool API KEY; SaaS = per
// capability). Positively confirm 'ce'; default to SaaS/unknown on uncertainty.
const isCe = ref(false)
async function loadEdition() {
  try {
    const cfg = await configService.fetchConfig()
    // eslint-disable-next-line giljo-internal/no-scattered-mode-checks
    isCe.value = cfg?.giljo_mode === 'ce'
  } catch {
    isCe.value = false
  }
}
onMounted(loadEdition)

// FE-9569 detector 2: a wizard resumed DIRECTLY onto Install leaves
// connectedTools empty forever (see the composable's doc comment).
useConnectedToolsResumeSeed({
  currentStep: () => props.currentStep,
  selectedTools: () => localSelectedTools.value,
  step2Data,
})

function toolMethodTag(toolId) {
  return methodTag(toolId, isCe.value)
}

function handleRestartConfirmed() {
  showRestartConfirm.value = false
  localSelectedTools.value = []
  emit('update:currentStep', 0)
}

// Sync when prop changes externally
watch(
  () => props.selectedTools,
  (newVal) => {
    localSelectedTools.value = [...newVal]
  },
)

// Connected tools from Step 2 data, passed to Step 3
const step2ConnectedTools = computed(() => step2Data.value?.connectedTools || [])

// Connect-stage rail sub-rows: one per selected tool, state from the walk
// (done = connected, current = tool being walked, ahead = not yet reached).
const connectSubRows = computed(() => {
  const w = step2WalkState.value
  if (!w?.order?.length) return []
  return w.order.map((id) => {
    let state = 'ahead'
    if (w.conn?.[id] === 'connected') state = 'done'
    else if (id === w.activeId) state = 'current'
    return {
      id,
      name: toolName(id),
      state,
      statusText: state === 'done' ? 'CONNECTED' : state === 'current' ? 'WAITING' : '',
    }
  })
})

// Rail: spine fill height tracks progress (0 → 100%, 3 gaps for 4 steps).
const spineFillPct = computed(() => (Math.min(props.currentStep, 3) / 3) * 100)

// Rail nodes: only completed (done) steps are clickable — mirrors the
// authoritative pixel spec (see the design-system reference).
function goToStep(i) {
  if (i < props.currentStep) {
    emit('update:currentStep', i)
  }
}

// Footer skip control (steps 1 & 2 only). Centralized here so both steps
// share one footer element instead of each child owning its own skip link.
const footerSkipLabel = computed(() => {
  if (props.currentStep === 1) return 'Skip for now'
  if (props.currentStep === 2) return "Skip, I'll do this later"
  return ''
})

const footerSkipTestId = computed(() => {
  if (props.currentStep === 1) return 'connect-skip'
  if (props.currentStep === 2) return 'install-skip'
  return null
})

function handleFooterSkip() {
  if (props.currentStep === 1) handleStep2Skip()
  else if (props.currentStep === 2) handleStep3Skip()
}

function toggleTool(toolId) {
  const index = localSelectedTools.value.indexOf(toolId)
  if (index === -1) {
    localSelectedTools.value.push(toolId)
  } else {
    localSelectedTools.value.splice(index, 1)
  }
}

function isSelected(toolId) {
  return localSelectedTools.value.includes(toolId)
}

const canProceed = computed(() => {
  if (props.currentStep === 0) {
    return localSelectedTools.value.length > 0
  }
  if (props.currentStep === 1) {
    return step2CanProceed.value
  }
  if (props.currentStep === 2) {
    return step3CanProceed.value
  }
  // Step 3 (Launch) has its own card-based navigation
  return false
})

function handleNext() {
  if (!canProceed.value) return

  if (props.currentStep === 0) {
    emit('step-complete', { step: 0, data: { tools: [...localSelectedTools.value] } })
  } else if (props.currentStep === 1) {
    emit('step-complete', { step: 1, data: { ...step2Data.value } })
  } else if (props.currentStep === 2) {
    emit('step-complete', { step: 2, data: { ...step3Data.value } })
  } else {
    emit('step-complete', { step: props.currentStep, data: {} })
  }

  if (props.currentStep < STEPS.length - 1) {
    emit('update:currentStep', props.currentStep + 1)
  }
}

function handleBack() {
  if (props.currentStep > 0) {
    emit('update:currentStep', props.currentStep - 1)
  }
}

function handleStep2Skip() {
  // User opts out of connecting now (e.g. OAuth-incapable harness, HTTP-on-LAN,
  // or they'll wire it up later). Advance past the MCP-attach step without
  // requiring a live connection. Mirrors the Install step's skip.
  emit('step-complete', { step: 1, data: { connectedTools: [], skipped: true } })
  if (props.currentStep < STEPS.length - 1) {
    emit('update:currentStep', props.currentStep + 1)
  }
}

function handleStep3Skip() {
  emit('step-complete', { step: 2, data: { installedTools: [], skipped: true } })
  if (props.currentStep < STEPS.length - 1) {
    emit('update:currentStep', props.currentStep + 1)
  }
}

function handleFinish() {
  emit('step-complete', { step: 3, data: { action: 'home', route: '/home', setup_complete: true } })
  handleDismiss()
}

const closingWithCheckmarks = ref(false)

function handleDismiss() {
  // If setup is already done and we're on the final step, show all-complete state then auto-close
  if (props.mode === 'setup' && props.currentStep === 3 && !closingWithCheckmarks.value) {
    closingWithCheckmarks.value = true
    // Force all steps to show as completed visually
    emit('update:currentStep', 4)
    setTimeout(() => {
      closingWithCheckmarks.value = false
      emit('dismiss')
      emit('update:modelValue', false)
      // Reset back to step 3 for next open
      emit('update:currentStep', 3)
    }, 1200)
    return
  }
  emit('dismiss')
  emit('update:modelValue', false)
}
</script>

<style scoped lang="scss">
@use '../../styles/variables' as *;
@use '../../styles/design-tokens' as *;
@use '../../styles/setup-wizard-shared' as wiz;

// Steps 0/2/3 float their body vertically below the (top-pinned) title.
// Step 1 (Connect) has no wrapper — content-heavy, flows top-down.
@include wiz.setup-wiz-center;

/* Overlay transition */
.overlay-fade-enter-active {
  transition: opacity 250ms ease-out;
}

.overlay-fade-leave-active {
  transition: opacity 200ms ease-in;
}

.overlay-fade-enter-from,
.overlay-fade-leave-to {
  opacity: 0;
}

/* Full viewport overlay */
.setup-wizard-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

/* Semi-transparent backdrop */
.setup-wizard-backdrop {
  position: absolute;
  inset: 0;
  background: rgba($color-background-primary, 0.85);
}

/* ============================================================
   SETUP MODE — Gradient Rail (FE-6259b)
   ============================================================ */

.wizard-rail-panel {
  position: relative;
  width: 100%;
  max-width: 900px;
  min-height: 540px;
  max-height: calc(100vh - 48px);
  overflow: hidden;
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
  display: grid;
  grid-template-columns: 258px 1fr;
}

.wizard-rail-close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 5;
}

/* ── Closing state (all-complete checkmark) ── */
.closing-confirmation {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  gap: 12px;
  animation: closing-fade-in 0.4s ease;
}

.closing-icon {
  animation: closing-scale 0.5s ease;
}

.closing-text {
  font-size: 1.1rem;
  font-weight: 500;
  color: rgb(var(--v-theme-success));
}

@keyframes closing-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes closing-scale {
  0% { transform: scale(0.5); opacity: 0; }
  60% { transform: scale(1.15); }
  100% { transform: scale(1); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .closing-confirmation,
  .closing-icon {
    animation: none;
  }
}

/* ── Left rail ── */
.wizard-rail {
  background: $color-background-tertiary;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  padding: 26px 20px;
  position: relative;
  overflow-y: auto;
}

.rail-top {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-bottom: 28px;
}

.rail-logo {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
}

.rail-title {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 700;
  font-size: 1.05rem;
  line-height: 1.1;
  background: var(--gradient-brand);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.rail-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-top: 3px;
}

.stepper {
  position: relative;
  padding-left: 4px;
}

.spine {
  position: absolute;
  left: 19px;
  top: 12px;
  bottom: 12px;
  width: 3px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.spine-fill {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 0;
  border-radius: 3px;
  background: var(--gradient-brand);
  transition: height 0.4s cubic-bezier(0.4, 0.9, 0.3, 1);
}

@media (prefers-reduced-motion: reduce) {
  .spine-fill {
    transition: none;
  }
}

.rail-node {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 13px;
  padding: 11px 8px 11px 0;
  border-radius: 10px;
  cursor: default;
}

.rail-node--clickable {
  cursor: pointer;
}

.rail-node--clickable:hover {
  background: rgba(255, 255, 255, 0.03);
}

.rail-node--clickable:focus-visible {
  outline: 2px solid rgba(255, 195, 0, 0.55);
  outline-offset: 2px;
}

.rail-dot {
  position: relative;
  z-index: 1;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: $elevation-raised;
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.12);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.76rem;
  font-weight: 600;
  color: var(--text-muted);
  transition: box-shadow 0.25s, background 0.25s, color 0.25s;
}

@media (prefers-reduced-motion: reduce) {
  .rail-dot {
    transition: none;
  }
}

.rail-node--active .rail-dot {
  box-shadow: inset 0 0 0 2px var(--nodecol), 0 0 0 4px color-mix(in srgb, var(--nodecol) 22%, transparent);
  color: var(--nodecol);
  background: color-mix(in srgb, var(--nodecol) 12%, $elevation-raised);
}

.rail-node--done .rail-dot {
  background: var(--nodecol);
  color: $color-on-brand-ink;
  box-shadow: none;
}

.rail-node-label {
  display: block;
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  font-size: 0.88rem;
  color: $lightest-blue;
  transition: color 0.2s;
}

.rail-node--active .rail-node-label,
.rail-node--done .rail-node-label {
  color: $color-text-primary;
}

.rail-node-desc {
  display: block;
  font-size: 0.7rem;
  color: var(--text-muted);
  margin-top: 1px;
}

/* ── Right: main content + footer ── */
.wizard-main {
  display: flex;
  flex-direction: column;
  padding: 26px 30px 22px;
  min-width: 0;
}

.wizard-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
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
  margin: 0 auto 20px;
  max-width: 40rem;
}

.step-fineprint {
  text-align: center;
  font-size: 0.74rem;
  color: var(--text-muted);
  margin: 16px auto 0;
  max-width: 46rem;
  line-height: 1.5;
}

/* Tools grid: 2x3 for the six-tool choose step (FE-9204). */
.tools-grid--six {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

@media (max-width: 640px) {
  .tools-grid--six {
    grid-template-columns: 1fr;
  }
}

/* Row card: icon well + name/method + check ring. */
.tool-card--row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 16px 18px;
  border-radius: $border-radius-md;
  background: $elevation-elevated;
  cursor: pointer;
  user-select: none;
  transition: transform 0.15s, box-shadow 0.15s;
}

.tool-card--row:hover {
  transform: translateY(-1px);
  --smooth-border-color: #{rgba($color-brand-yellow, 0.4)};
}

.tool-card--row:focus-visible {
  outline: 2px solid $color-brand-yellow;
  outline-offset: 2px;
}

.tool-card--sel {
  --smooth-border-color: #{$color-brand-yellow};
  box-shadow: inset 0 0 0 2px $color-brand-yellow, 0 0 16px rgba($color-brand-yellow, 0.12) !important;
  background: rgba($color-brand-yellow, 0.05);
}

.tool-card-well {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: $border-radius-default;
  background: rgba(255, 255, 255, 0.05);
  display: grid;
  place-items: center;
  color: $lightest-blue;
}

.tool-card-logo {
  width: 22px;
  height: 24px;
  object-fit: contain;
}

.tool-card-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.tool-name {
  font-family: 'Outfit', $typography-font-primary;
  font-size: 0.9rem;
  font-weight: 600;
  color: $color-text-primary;
}

.tool-method {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.56rem;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.tool-card-ring {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.15);
}

.tool-card-ring--on {
  background: rgba($color-brand-yellow, 0.16);
  color: $color-brand-yellow;
  box-shadow: none;
  animation: ring-pop 0.35s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes ring-pop {
  0% { transform: scale(0.6); opacity: 0; }
  60% { transform: scale(1.15); }
  100% { transform: scale(1); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .tool-card-ring--on {
    animation: none;
  }
}

/* Connect-stage rail sub-rows */
.rail-subs {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 0 0 4px 43px;
}

.rail-sub {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 6px 8px;
  border-radius: 8px;
}

.rail-sub-dot {
  width: 7px;
  height: 7px;
  flex-shrink: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
}

.rail-sub-dot--done {
  background: $color-status-success;
}

.rail-sub-dot--current {
  background: $color-indicator-disconnected;
  animation: rail-sub-wait 1.6s ease infinite;
}

@keyframes rail-sub-wait {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
}

@media (prefers-reduced-motion: reduce) {
  .rail-sub-dot--current {
    animation: none;
  }
}

.rail-sub-label {
  flex: 1;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem;
  color: var(--text-muted);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rail-sub-dot--current + .rail-sub-label {
  color: $lightest-blue;
}

.rail-sub-status {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.52rem;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}

/* ── Footer ── */
.wz-footer {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 14px;
  margin-top: 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.footer-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.footer-spacer {
  flex: 1;
}

.footer-back {
  color: $lightest-blue !important;
}

.footer-restart {
  color: var(--text-muted) !important;
}

.footer-next-btn {
  border-radius: $border-radius-default;
  min-width: 100px;
  font-weight: 600;
  // Gradient Next/Finish per the locked spec (mockup .btn-grad): brand ramp
  // fill with dark on-brand ink. !important overrides Vuetify's flat surface.
  background: var(--gradient-brand) !important;
  color: $color-on-brand-ink !important;
}

// A disabled Next must NOT read as the live brand pill (FE-9497): drop the
// gradient for a flat muted surface so "you cannot continue yet" is legible.
.footer-next-btn.v-btn--disabled {
  background: $elevation-elevated !important;
  color: $color-text-muted !important;
  box-shadow: none !important;
  opacity: 1;
}

.footer-skip {
  text-align: right;
}

.skiplink {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.8125rem;
  color: var(--text-muted);
  padding: 2px 0;
  font-family: inherit;
  transition: color 150ms ease-out;
}

.skiplink:hover,
.skiplink:focus-visible {
  color: $color-brand-yellow;
  text-decoration: underline;
  text-underline-offset: 2px;
}

/* Responsive: rail collapses above content on narrow viewports */
@media (max-width: 720px) {
  .wizard-rail-panel {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .wizard-rail {
    border-right: none;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }

  .spine,
  .spine-fill {
    display: none;
  }
}

/* Responsive: mobile */
@media (max-width: 599px) {
  .setup-wizard-overlay {
    padding: 12px;
  }

  .wizard-rail {
    padding: 18px 16px;
  }

  .wizard-main {
    padding: 18px 16px 16px;
  }
}
</style>
