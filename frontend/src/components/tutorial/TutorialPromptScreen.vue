<template>
  <div class="prompt-screen">
    <div class="beat-eyebrow">{{ meta.eyebrow }}</div>
    <h2 class="beat-title">{{ meta.title }}</h2>
    <p class="beat-sub">{{ meta.sub }}</p>

    <div class="prompt-box" data-testid="tutorial-prompt-text">{{ promptText }}</div>

    <div class="prompt-actions">
      <!-- FE-9569 Part 2: kept visible as a restart path even once the agent
           starts populating the product (operator's open question, answered
           in the PR body: keep it, demote its styling). Demoting means it no
           longer reads as the NEXT action once real progress is visible
           elsewhere on the card. -->
      <v-btn
        :color="path === 'D' && agentActive ? undefined : 'primary'"
        :variant="path === 'D' && agentActive ? 'outlined' : 'flat'"
        class="copy-btn"
        :class="{ 'copy-btn--demoted': path === 'D' && agentActive }"
        data-testid="tutorial-copy-prompt"
        :disabled="path === 'D' && createFailed"
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
      <!-- FE-9569 detector 3: enhanced visibility -- a halo ring around the
           dot plus bolder text, so this is not just one small pulsing dot
           easy to miss while the agent works. -->
      <span v-else-if="path === 'D' && !createFailed" class="agent-waiting" data-testid="tutorial-agent-waiting">
        <span class="waiting-dot-wrap">
          <span class="waiting-dot-ring" />
          <span class="waiting-dot" />
        </span>
        Waiting for your agent…
      </span>
    </div>

    <p class="prompt-hint">{{ meta.hint }}</p>

    <!-- FE-9566: door D pre-creates the card the agent fills in. When that
         cannot be done, say so here rather than leaving the user on a prompt
         whose product does not exist — the old code swallowed the reason and
         showed the ordinary "Waiting for your agent…" line forever. -->
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

    <!-- FE-9320: door D waited on a connected agent forever with no hint at all,
         and the wizard lets the Connect and Install steps be skipped — so after
         a minute, say plainly what this step needs and offer a way out. Door B
         needs no connection (any chat tool) and already has its own forward
         control, so this is D-only. -->
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
  /** Router door: 'D' (existing codebase) or 'B' (guided interview). */
  path: {
    type: String,
    required: true,
    validator: (v) => v === 'D' || v === 'B',
  },
  /** THE tutorial-run product id, threaded via useTutorialState (gate F1). */
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
// FE-9430: named apart from the `productId` PROP on purpose. When a ref shares
// a prop's name, `<script setup>` exposes the ref to the template and the prop
// becomes unreachable from it — the same silent-shadowing failure FE-9419 hit
// from the other direction. This ref is the run's WORKING id: seeded from
// props.productId when the run threads one, otherwise adopted or created here.
const activeProductId = ref('')
const agentDone = ref(false)
const copied = ref(false)
// FE-9569 Part 2: true the first time a fetched product row shows ANY real
// content (any progressive-fill section, not just the final consolidated
// write) -- demotes the Copy-prompt button's styling so it stops reading as
// the next action once the card is visibly filling in. Never reverts once
// true: it is a restart path, not a live "is it still going" indicator.
const agentActive = ref(false)
// FE-9566: door D could not get a product for this run (create rejected, or it
// returned no row). Drives the visible error + retry; nothing else on the
// screen is trustworthy while it is true.
const createFailed = ref(false)
const retrying = ref(false)

const promptText = computed(() =>
  props.path === 'D'
    ? buildPromptD({ productId: activeProductId.value, saas: isSaasMode() })
    : buildPromptB({ saas: isSaasMode() }),
)

let copiedTimer = null
async function copyPrompt() {
  const ok = await copy(promptText.value)
  if (!ok) return
  copied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => {
    copied.value = false
  }, 1500)
}

// ── Path D "agent is done" DONE-SIGNAL SEAM ──────────────────────────────────
// agentReportsDone() is the SINGLE decision point for "the agent's pass is
// complete" — every signal (WS event AND poll tick AND mount check) funnels
// a freshly fetched product row through it.
//
// PROGRESSIVE-FILL contract (design ruling): Prompt-D writes
// the card section by section (Info → Tech → Arch → Testing) and the
// consolidated vision LAST. Intermediate writes only refresh the card display
// (each WS event/poll tick re-fetches the row into the store) — ONLY the
// final consolidated-vision write advances to review. NOT the
// vision_analysis_complete flag: with zero uploaded docs the evaluator never
// flips it (requires >=1 active doc — locked by
// tests/test_fe9200_tutorial_prompt_contract.py).
function agentReportsDone(product) {
  return Boolean(product?.consolidated_vision_light)
}

/** True once the fetched row shows ANY real content the agent wrote -- Info,
 *  Tech, Architecture, or Testing/quality (whichever section it did first;
 *  the prompt does not guarantee an order the UI can rely on beyond
 *  consolidated_vision being last). Deliberately looser than
 *  agentReportsDone: this only decides button STYLING, never navigation. */
function productHasActivity(product) {
  if (!product) return false
  if ((product.name || '').trim()) return true
  if ((product.description || '').trim()) return true
  const ts = product.tech_stack || {}
  return Object.values(ts).some((v) => (Array.isArray(v) ? v.length > 0 : Boolean(String(v || '').trim())))
}

// LIVE signal: update_product_fields emits vision:analysis_complete on every
// write (post-commit) — caught below via the window event, then verified
// through the seam. POLL fallback: FE-9166 idiom, 10s.
const POLL_INTERVAL_MS = 10_000
let pollTimer = null
let pollInFlight = false

// FE-9320: mirrors the upload screen's 60s hint so both agent-driven doors are
// honest about needing a connected agent, instead of only door A being so.
const STALL_HINT_MS = 60_000
const stalled = ref(false)
let stallTimer = null

function markAgentDone() {
  if (agentDone.value) return
  agentDone.value = true
  clearTimeout(stallTimer)
  stopPolling()
  // Surface the "reports done" line, then advance to review.
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
  // The event only says "a write landed" — the seam decides whether the pass
  // is COMPLETE (guards progressive fill's intermediate writes).
  try {
    const updated = await productStore.fetchProductById(activeProductId.value)
    if (!agentActive.value && productHasActivity(updated)) agentActive.value = true
    if (agentReportsDone(updated)) markAgentDone()
  } catch {
    // Poll fallback keeps running.
  }
}

// Path D needs an existing product card for the agent to populate: the
// silent-create idiom (useProductVisionUpload), created with an EMPTY name so
// the agent can set product_name from the repo (merge-write only skips fields
// that are already non-empty).
//
// GATE F1: only a product THIS RUN owns may drive the flow. The threaded
// s.productId is authoritative; absent that, we may adopt ONLY a previous
// tutorial draft — one with no NAME, because user-created products always
// carry a name. NEVER products[0]: the list is ordered is_active.desc, so
// [0] is the user's real product whenever one exists — selecting it would
// present it as "proposed" and let Activate deactivate it.
//
// FE-9566: this gate also required `!p.is_active`, written when is_active
// meant "THE active product". FE-9524/D1 redefined it as "shown as a tab",
// and create_product sets it True for every product, a nameless draft
// included — so that half stopped excluding the user's product and started
// excluding the drafts this gate exists to adopt. The door then always tried
// to CREATE and collided with its own leftover on the second visit. The NAME
// check is, and always was, the half carrying the protection.
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

  // FE-9566: every outcome below used to be swallowed — a rejected create, a
  // rejected fallback, and a create that RESOLVED with no row all ended as
  // activeProductId='' with the screen carrying on as though it had a product.
  // The user was left on a prompt whose product does not exist, and the prompt
  // interpolates the id, so copying it points their agent at product_id "".
  // "No id, whatever the reason" is the single failure condition.
  let failure = null
  try {
    const product = await productStore.createProduct({ name: '' })
    activeProductId.value = product?.id || ''
  } catch (emptyNameError) {
    // Fall back to a named draft if the backend rejects an empty name; the
    // user can rename it from the product form afterwards.
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

// FE-9566: the retry the error state offers. Guarded against double-fire so a
// second click cannot start a concurrent create while the first is in flight.
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
