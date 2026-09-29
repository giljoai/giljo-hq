<template>
  <div class="prompt-screen">
    <div class="beat-eyebrow">{{ meta.eyebrow }}</div>
    <h2 class="beat-title">{{ meta.title }}</h2>
    <p class="beat-sub">{{ meta.sub }}</p>

    <div class="prompt-box" data-testid="tutorial-prompt-text">{{ promptText }}</div>

    <div class="prompt-actions">
      <v-btn
        :color="path === 'D' && agentActive ? undefined : 'primary'"
        :variant="path === 'D' && agentActive ? 'outlined' : 'flat'"
        class="copy-btn"
        :class="{ 'copy-btn--demoted': path === 'D' && agentActive }"
        data-testid="tutorial-copy-prompt"
        :disabled="path === 'D' && !copyReady"
        :aria-describedby="savingProduct ? SAVING_HINT_ID : undefined"
        :prepend-icon="copied ? 'mdi-check' : 'mdi-content-copy'"
        @click="copyPrompt"
      >
        {{ copied ? 'Copied' : 'Copy prompt' }}
      </v-btn>

      <v-btn
        v-if="path === 'B'"
        variant="text"
        class="continue-btn"
        data-testid="tutorial-b-upload"
        prepend-icon="mdi-file-upload-outline"
        @click="$emit('upload')"
      >
        I have my vision document
      </v-btn>

      <span v-if="path === 'D' && agentDone && !createFailed" class="agent-done" data-testid="tutorial-agent-done">
        Your agent reports done — review it
      </span>
      <span
        v-else-if="savingProduct"
        :id="SAVING_HINT_ID"
        class="prompt-saving"
        role="status"
        data-testid="tutorial-prompt-saving"
      >
        Saving your product…
      </span>
      <span v-else-if="path === 'D' && !createFailed" class="agent-waiting" data-testid="tutorial-agent-waiting">
        <span class="waiting-dot-wrap">
          <span class="waiting-dot-ring" />
          <span class="waiting-dot" />
        </span>
        Waiting for your agent…
      </span>
    </div>

    <p class="prompt-hint">{{ meta.hint }}</p>

    <div v-if="path === 'D' && createFailed" class="prompt-error" data-testid="tutorial-prompt-error">
      <p class="prompt-hint">
        {{ PRODUCT_NAME }} could not create the product card this step needs, so there is
        nothing for your agent to fill in yet. This is usually temporary.
      </p>
      <v-btn
        variant="text"
        class="stalled-btn"
        data-testid="tutorial-prompt-retry"
        :disabled="retrying"
        prepend-icon="mdi-refresh"
        @click="retryEnsureProduct"
      >
        {{ retrying ? 'Trying again…' : 'Try again' }}
      </v-btn>
      <v-btn
        variant="text"
        class="stalled-btn"
        data-testid="tutorial-prompt-error-manual"
        @click="$emit('manual')"
      >
        Fill it in myself instead
      </v-btn>
    </div>

    <div
      v-if="path === 'D' && stalled && !agentDone && !createFailed"
      class="prompt-stalled"
      data-testid="tutorial-prompt-stalled"
    >
      <p class="prompt-hint">
        Still nothing. This door only completes when an agent connected to {{ PRODUCT_NAME }}
        runs the prompt — if you skipped the connect step, or pasted it into a chat tool with
        no connection, it cannot report back. You can fill the product in yourself instead.
      </p>
      <v-btn
        variant="text"
        class="stalled-btn"
        data-testid="tutorial-prompt-manual"
        @click="$emit('manual')"
      >
        Fill it in myself instead
      </v-btn>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useProductStore } from '@/stores/products'
import { useClipboard } from '@/composables/useClipboard'
import { useGiljoMode } from '@/composables/useGiljoMode'
import { PROMPT_META, buildPromptB, buildPromptD } from '@/content/onboarding/prompts'
import { PRODUCT_NAME } from '@/branding'

const props = defineProps({
  path: {
    type: String,
    required: true,
    validator: (v) => v === 'D' || v === 'B',
  },
  productId: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['review', 'upload', 'product-created', 'manual'])

const productStore = useProductStore()
const { copy } = useClipboard()
const { isSaasMode } = useGiljoMode()

const meta = computed(() => PROMPT_META[props.path])
const activeProductId = ref('')
const agentDone = ref(false)
const copied = ref(false)
const agentActive = ref(false)
const createFailed = ref(false)
const retrying = ref(false)

const SAVING_HINT_ID = 'tutorial-prompt-saving-hint'
const copyReady = computed(() => Boolean(activeProductId.value) && !createFailed.value)
const savingProduct = computed(() => props.path === 'D' && !activeProductId.value && !createFailed.value)

const promptText = computed(() =>
  props.path === 'D'
    ? buildPromptD({ productId: activeProductId.value, saas: isSaasMode() })
    : buildPromptB({ saas: isSaasMode() }),
)

let copiedTimer = null
async function copyPrompt() {
  if (props.path === 'D' && !copyReady.value) return
  const ok = await copy(promptText.value)
  if (!ok) return
  copied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => {
    copied.value = false
  }, 1500)
}

function agentReportsDone(product) {
  return Boolean(product?.consolidated_vision_light)
}

function productHasActivity(product) {
  if (!product) return false
  if ((product.name || '').trim()) return true
  if ((product.description || '').trim()) return true
  const ts = product.tech_stack || {}
  return Object.values(ts).some((v) => (Array.isArray(v) ? v.length > 0 : Boolean(String(v || '').trim())))
}

const POLL_INTERVAL_MS = 10_000
let pollTimer = null
let pollInFlight = false

const STALL_HINT_MS = 60_000
const stalled = ref(false)
let stallTimer = null

function markAgentDone() {
  if (agentDone.value) return
  agentDone.value = true
  clearTimeout(stallTimer)
  stopPolling()
  setTimeout(() => emit('review'), 1200)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  pollInFlight = false
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (pollInFlight || !activeProductId.value) return
    pollInFlight = true
    try {
      const updated = await productStore.fetchProductById(activeProductId.value)
      if (!agentActive.value && productHasActivity(updated)) agentActive.value = true
      if (agentReportsDone(updated)) markAgentDone()
    } catch {
      // Transient poll failures are fine — next tick retries.
    } finally {
      pollInFlight = false
    }
  }, POLL_INTERVAL_MS)
}

async function onVisionComplete(event) {
  if (!event.detail?.product_id || event.detail.product_id !== activeProductId.value) return
  try {
    const updated = await productStore.fetchProductById(activeProductId.value)
    if (!agentActive.value && productHasActivity(updated)) agentActive.value = true
    if (agentReportsDone(updated)) markAgentDone()
  } catch {
    // Poll fallback keeps running.
  }
}

async function ensureProduct() {
  if (props.productId) {
    activeProductId.value = props.productId
    try {
      const row = await productStore.fetchProductById(props.productId)
      if (!agentActive.value && productHasActivity(row)) agentActive.value = true
      if (agentReportsDone(row)) markAgentDone()
    } catch {
      // Poll will retry.
    }
    return
  }

  const draft = productStore.products.find((p) => !(p.name || '').trim())
  if (draft) {
    activeProductId.value = draft.id
    emit('product-created', draft.id)
    return
  }

  let failure = null
  try {
    const product = await productStore.createProduct({ name: '' })
    activeProductId.value = product?.id || ''
  } catch (emptyNameError) {
    failure = emptyNameError
    try {
      const product = await productStore.createProduct({ name: 'My product' })
      activeProductId.value = product?.id || ''
    } catch (fallbackError) {
      failure = fallbackError
      activeProductId.value = ''
    }
  }

  if (activeProductId.value) {
    createFailed.value = false
    emit('product-created', activeProductId.value)
    return
  }
  createFailed.value = true
  console.error(
    '[tutorial] door D could not create a product for this run:',
    failure || 'the create call resolved without a product row',
  )
}

async function retryEnsureProduct() {
  if (retrying.value) return
  retrying.value = true
  try {
    await ensureProduct()
  } finally {
    retrying.value = false
  }
}

onMounted(async () => {
  if (props.path !== 'D') return
  await ensureProduct()
  if (!agentDone.value) {
    window.addEventListener('vision-analysis-complete', onVisionComplete)
    startPolling()
    stallTimer = setTimeout(() => { stalled.value = true }, STALL_HINT_MS)
  }
})

onBeforeUnmount(() => {
  stopPolling()
  clearTimeout(copiedTimer)
  clearTimeout(stallTimer)
  window.removeEventListener('vision-analysis-complete', onVisionComplete)
})
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

.prompt-screen {
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
  font-size: 26px;
  letter-spacing: -0.02em;
  color: $color-text-primary;
}

.beat-sub {
  margin: 0 0 14px;
  font-size: 14px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.prompt-box {
  background: $color-background-primary;
  border-radius: $border-radius-md;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  padding: 16px 18px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  line-height: 1.75;
  color: var(--text-secondary);
  white-space: pre-wrap;
  overflow-y: auto;
  min-height: 0;
}

.prompt-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 14px;
}

.copy-btn {
  font-family: 'Outfit', $typography-font-primary;
  font-weight: 600;
  border-radius: $border-radius-default;
  background: $color-brand-yellow !important;
  color: $color-on-yellow-ink !important;

  &:hover {
    background: $color-brand-yellow-hover !important;
  }
}

/* FE-9569 Part 2: demoted once the agent starts populating the product --
   still a real, clickable restart path, just no longer styled as THE next
   action once visible progress is happening elsewhere on the card. Same
   !important precedent as .copy-btn above (Vuetify's color/variant props
   apply inline styles that plain CSS specificity cannot beat). */
.copy-btn--demoted {
  background: transparent !important;
  color: var(--text-secondary) !important;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);

  &:hover {
    background: rgba(255, 255, 255, 0.04) !important;
  }
}

.continue-btn {
  color: var(--text-secondary) !important;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
  border-radius: $border-radius-default;
}

.prompt-saving {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  color: var(--text-secondary);
}

/* FE-9569 detector 3: bolder text (was --text-muted at 11px) -- the operator
   asked to enhance visibility, not just the dot. */
.agent-waiting {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.waiting-dot-wrap {
  position: relative;
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
}

.waiting-dot {
  position: relative;
  z-index: 1;
  width: 9px;
  height: 9px;
  border-radius: $border-radius-pill;
  background: $color-status-waiting;
  animation: tutorialPulse 1.6s ease infinite;
}

/* The halo ring IS the visibility fix: a single 8px dot was the operator's
   complaint ("easy to miss while the agent works"). An expanding, fading
   ring around it reads from across the room the way a lone static dot does
   not. */
.waiting-dot-ring {
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1px solid rgba($color-status-waiting, 0.6);
  animation: tutorialRing 1.6s ease infinite;
}

@keyframes tutorialPulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1; }
}

@keyframes tutorialRing {
  0% { transform: scale(0.6); opacity: 0.8; }
  100% { transform: scale(1.8); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .waiting-dot,
  .waiting-dot-ring {
    animation: none;
  }
}

.agent-done {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: $color-status-complete;
}

.prompt-hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.prompt-stalled {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

/* FE-9566: same shape as .prompt-stalled — this is the same kind of "the step
   cannot proceed" aside — but carries the error accent, because unlike the
   stall hint this is a failure that already happened, not a slow wait. */
.prompt-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  border-left: 2px solid $color-status-error;
  padding-left: 10px;
}

.stalled-btn {
  color: var(--text-secondary) !important;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.14);
  border-radius: $border-radius-default;
}
</style>
