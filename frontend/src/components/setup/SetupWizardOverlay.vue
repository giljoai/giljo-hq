<template>
  <Teleport to="body">
    <Transition name="overlay-fade">
      <div
        v-if="modelValue"
        class="setup-wizard-overlay"
        :style="{ right: `${guide.reservedWidth}px` }"
        data-testid="setup-wizard-overlay"
        role="dialog"
        aria-modal="true"
        :aria-label="setupAriaLabel"
        @keydown.escape="handleDismiss"
      >
        <div class="setup-wizard-backdrop" />

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

          <aside class="wizard-rail">
            <div class="rail-top">
              <img src="/icons/Giljo_YW_Face.svg" alt="" class="rail-logo" />
              <div>
                <div class="rail-title">Set up Giljo HQ</div>
                <div class="rail-count">Step {{ currentStep + 1 }} of {{ STEPS.length }}</div>
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

          <main class="wizard-main">
            <div class="wizard-content" data-testid="wizard-content">
              <div v-if="currentStep === 0" class="step-tools">
                <p class="step-heading-grad">Choose your tools</p>
                <p class="step-sub">
                  Which AI coding agent(s) do you use? Pick one or more. You can add the rest later.
                </p>

                <div class="wiz-center">
                  <div class="tools-grid tools-grid--six">
                    <div
                      v-for="tool in visibleTools"
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
                        <span
                          v-if="connectedToolIds.has(tool.id)"
                          class="tool-connected"
                          :data-testid="`tool-connected-${tool.id}`"
                        >Connected</span>
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

              <SetupStep2Connect
                v-else-if="currentStep === 1"
                :selected-tools="localSelectedTools"
                @can-proceed="step2CanProceed = $event"
                @step-data="step2Data = $event"
                @walk-state="step2WalkState = $event"
                @advance-step="handleNext"
              />

              <SetupStep3Commands v-else-if="currentStep === 2" :tools="localSelectedTools" />

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

                <v-btn
                  color="primary"
                  variant="flat"
                  class="footer-next-btn"
                  data-testid="setup-next-btn"
                  :disabled="!canProceed"
                  @click="handleNext"
                >
                  {{ isLastStep ? 'Done' : 'Next' }}
                </v-btn>
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
        </div>
      </div>
    </Transition>

  </Teleport>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import configService from '@/services/configService'
import { setupToolsFor, methodTag, toolName } from '@/config/setupTools'
import { useHostedAppPreselect } from '@/composables/useHostedAppPreselect'
import { PRODUCT_NAME } from '@/branding'
import { useGuideStore } from '@/stores/guide'
import { useConnectedToolIds } from '@/composables/useConnectedToolIds'
import SetupStep2Connect from './SetupStep2Connect.vue'
import SetupStep3Commands from './SetupStep3Commands.vue'
const guide = useGuideStore()

const setupAriaLabel = `Setup ${PRODUCT_NAME}`

const STEPS = [
  { id: 'tools', label: 'Choose tool' },
  { id: 'connect', label: 'Connect it' },
  { id: 'setup', label: 'Setup instructions' },
]

const STEP_DESC = ['Pick your AI agents', 'Attach them to Giljo HQ', 'Get your tool ready']

const STEP_COLORS = ['var(--gradient-step-1)', 'var(--gradient-step-3)', 'var(--gradient-step-4)']

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
  fresh: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits([
  'update:modelValue',
  'update:currentStep',
  'dismiss',
  'step-complete',
])

const localSelectedTools = ref(props.fresh ? [] : [...props.selectedTools])
const { connected: connectedToolIds, reload: reloadConnected } = useConnectedToolIds()
const step2CanProceed = ref(false)
const step2Data = ref({})
const step2WalkState = ref(null)

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
const visibleTools = computed(() => setupToolsFor(isCe.value))

useHostedAppPreselect({
  currentStep: () => props.currentStep,
  savedTools: () => props.selectedTools,
  selected: localSelectedTools,
  visibleTools: () => visibleTools.value,
  enabled: () => !props.fresh,
})

function toolMethodTag(toolId) {
  return methodTag(toolId, isCe.value)
}

watch(
  () => props.selectedTools,
  (newVal) => {
    localSelectedTools.value = props.fresh ? [] : [...newVal]
  },
)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    if (props.fresh) localSelectedTools.value = []
    reloadConnected()
  },
)

const connectSubRows = computed(() => {
  const w = step2WalkState.value
  if (!w?.order?.length) return []
  return w.order.map((id) => {
    let state = 'ahead'
    if (w.conn?.[id] === 'connected') state = 'done'
    else if (id === w.activeId && w.conn?.[id] !== 'connected_before') state = 'current'
    return {
      id,
      name: toolName(id),
      state,
      statusText: state === 'done' ? 'CONNECTED' : w.conn?.[id] === 'connected_before' ? 'CONNECTED BEFORE' : state === 'current' ? 'WAITING' : '',
    }
  })
})

const isLastStep = computed(() => props.currentStep === STEPS.length - 1)

const spineFillPct = computed(() => (props.currentStep / (STEPS.length - 1)) * 100)

function goToStep(i) {
  if (i < props.currentStep) {
    emit('update:currentStep', i)
  }
}

const footerSkipLabel = computed(() => (props.currentStep === 1 ? 'Skip for now' : ''))
const footerSkipTestId = computed(() => (props.currentStep === 1 ? 'connect-skip' : null))

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
  return true
})

function handleNext() {
  if (!canProceed.value) return

  if (props.currentStep === 0) {
    emit('step-complete', { step: 0, data: { tools: [...localSelectedTools.value] } })
    emit('update:currentStep', 1)
    return
  }
  if (props.currentStep === 1) {
    emit('step-complete', { step: 1, data: { ...step2Data.value } })
    emit('update:currentStep', 2)
    return
  }
  emit('step-complete', { step: 2, data: {} })
  handleDismiss()
}

function handleBack() {
  if (props.currentStep > 0) {
    emit('update:currentStep', props.currentStep - 1)
  }
}

function handleFooterSkip() {
  emit('step-complete', { step: 1, data: { connectedTools: [], skipped: true } })
  handleDismiss()
}

function handleDismiss() {
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
  background: $elevation-elevated;
  border-radius: $border-radius-rounded;
  display: grid;
  grid-template-columns: 258px 1fr;
}

.wizard-rail-panel.smooth-border {
  box-shadow: inset 0 0 0 2px rgba($color-brand-yellow, 0.55), 0 24px 64px rgba(0, 0, 0, 0.7);
}

.wizard-rail-close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 5;
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

@include wiz.setup-tool-cards;

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
</style>
