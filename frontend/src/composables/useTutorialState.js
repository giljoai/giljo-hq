/**
 * useTutorialState.js — onboarding tutorial state machine + persistence (FE-9200).
 *
 * Ports the state machine of the ratified onboarding-tutorial mock
 * into the app:
 *
 *   screen: 'beats' | 'prompt' | 'upload' | 'review' | 'done'
 *   beat:   1..6 while screen === 'beats' (6 = the router)
 *   path:   null | 'A' | 'B' | 'C' | 'D'  (router door choice)
 *
 * Persistence: `learning_complete` via PATCH /me/setup-state (existing field).
 * `learning_beat` / `router_choice` are SENT on every persist but are a
 * proposed schema addition (BE-9201, in flight): the endpoint's request model
 * ignores unknown fields today, so we feature-detect from the PATCH response —
 * if the backend does not echo `learning_beat` back, we stop sending the two
 * extra fields and degrade to learning_complete-only persistence.
 */
import { reactive, computed } from 'vue'
import { useProductStore } from '@/stores/products'
import { useUserStore } from '@/stores/user'

/** Rail stop labels — copy verbatim from the approved mock. */
export const TUTORIAL_STOPS = Object.freeze([
  'How it works',
  'Product & crew',
  'Missions',
  '360 Memory',
  'The destination',
  'Get started',
])

// ── Path-C activate breadcrumb (flagged code change #3) ─────────────────────
// A persistent, dismissible "Next: activate your product" nudge on Home and
// Products, armed when the user leaves the tutorial for the manual form and
// cleared on dismissal or first activation. localStorage (not server state) —
// same class of persistence as the cert-modal "don't show again" flag.
const BREADCRUMB_KEY = 'giljo_tutorial_activate_breadcrumb'

// FE-9320: the nudge is rendered by SystemStatusBanner, which DefaultLayout
// mounts OUTSIDE <router-view> with no :key — so it never remounts and read the
// armed flag exactly once, at app start. Arming afterwards (which is the only
// time it is ever armed: on the way out of the tutorial) was therefore inert for
// the rest of the session. Announcing the arming on the window lets that
// long-lived banner re-read the flag. Same idiom as 'api-key-created'; the
// listener is in SystemStatusBanner.vue and imports the constant below.
//
// Exported as the single source of truth rather than repeated as a literal: this
// event is the ONLY thing that reaches the banner once it is mounted, so if one
// side's spelling drifted the nudge would silently stop appearing while each
// side's tests kept passing against their own copy of the string.
export const ACTIVATE_BREADCRUMB_ARMED_EVENT = 'tutorial-activate-breadcrumb-armed'

export function armActivateBreadcrumb() {
  try {
    localStorage.setItem(BREADCRUMB_KEY, '1')
  } catch {
    /* storage unavailable — nudge simply won't persist */
  }
  window.dispatchEvent(new Event(ACTIVATE_BREADCRUMB_ARMED_EVENT))
}

export function clearActivateBreadcrumb() {
  try {
    localStorage.removeItem(BREADCRUMB_KEY)
  } catch {
    /* ignore */
  }
}

export function isActivateBreadcrumbArmed() {
  try {
    return localStorage.getItem(BREADCRUMB_KEY) === '1'
  } catch {
    return false
  }
}

const BEAT_MIN = 1
const BEAT_MAX = 6

// ── Abandoned-draft emptiness check (walkthrough fix 4) ─────────────────────
const hasText = (value) => typeof value === 'string' && value.trim().length > 0

/** Any non-empty string / non-empty array inside a card section counts as
 *  content. Numbers are ignored: test_config carries a coverage_target that
 *  defaults to 80 on untouched rows. */
function sectionHasContent(section) {
  if (!section || typeof section !== 'object') return false
  return Object.values(section).some(
    (value) => hasText(value) || (Array.isArray(value) && value.length > 0),
  )
}

/**
 * True only for a completely untouched pre-created draft: no name, no
 * description, no vision documents, no tech/arch/testing content — nothing.
 * ANY agent-written or user-entered data means the product must be kept
 * (which also makes a delete racing a first agent write harmless: non-empty
 * means no delete).
 */
function isDraftUntouched(product) {
  if (!product) return false
  if (
    hasText(product.name) ||
    hasText(product.description) ||
    hasText(product.project_path) ||
    hasText(product.core_features) ||
    hasText(product.brand_guidelines) ||
    hasText(product.consolidated_vision_light) ||
    hasText(product.consolidated_vision_medium)
  ) {
    return false
  }
  if (product.vision_analysis_complete || product.has_vision) return false
  if ((product.vision_documents_count ?? 0) > 0) return false
  return (
    !sectionHasContent(product.tech_stack) &&
    !sectionHasContent(product.architecture) &&
    !sectionHasContent(product.test_config)
  )
}

function clampBeat(value) {
  const n = Number.parseInt(value, 10)
  if (Number.isNaN(n)) return BEAT_MIN
  return Math.min(BEAT_MAX, Math.max(BEAT_MIN, n))
}

const VALID_PATHS = new Set(['A', 'B', 'C', 'D'])

export function useTutorialState() {
  const userStore = useUserStore()

  // Resume support (proposal §6): both fields only exist once the BE-9201
  // schema lands; absent keys fall back to a fresh start.
  const user = userStore.currentUser
  const s = reactive({
    beat: clampBeat(user?.learning_beat ?? BEAT_MIN),
    screen: 'beats',
    path: VALID_PATHS.has(user?.router_choice) ? user.router_choice : null,
    // THE tutorial product (gate F1): set once at creation/adoption on the
    // prompt/upload screens and read everywhere after — sub-screens must
    // NEVER re-derive products[0] (the list is ordered is_active.desc, so
    // [0] is the user's real ACTIVE product whenever one exists).
    productId: null,
  })

  // Feature detection for the proposed learning_beat/router_choice fields:
  // null = unknown (send + inspect response), false = backend ignores them.
  let beatSchemaSupported = null

  const railStop = computed(() => (s.screen === 'beats' ? s.beat : BEAT_MAX))
  const showBack = computed(
    () => s.screen === 'prompt' || s.screen === 'upload' || (s.screen === 'beats' && s.beat > BEAT_MIN),
  )
  const showNext = computed(() => s.screen === 'beats' && s.beat < BEAT_MAX)
  const nextLabel = computed(() => (s.beat === 5 ? 'Choose your start' : 'Next'))

  async function persist() {
    if (beatSchemaSupported === false) return
    try {
      // router_choice is a strict Literal["A","B","C","D"] on the backend
      // (BE-9201) — omit it entirely until a door has been picked.
      const payload = { learning_beat: s.beat }
      if (s.path) payload.router_choice = s.path
      const data = await userStore.updateSetupState(payload)
      if (beatSchemaSupported === null) {
        beatSchemaSupported = Boolean(data && 'learning_beat' in data)
      }
    } catch {
      // Persistence is best-effort; the tutorial keeps working in-session.
    }
  }

  /** Mark the tutorial finished (skip and done-screen entry both call this). */
  async function markComplete() {
    try {
      await userStore.updateSetupState({ learning_complete: true })
    } catch {
      // WelcomeView's dismiss handler is the safety net for this flag.
    }
  }

  function next() {
    if (s.screen !== 'beats' || s.beat >= BEAT_MAX) return
    s.beat += 1
    persist()
  }

  function back() {
    if (s.screen === 'prompt' || s.screen === 'upload') {
      // Back from a router sub-screen returns to the router itself.
      s.screen = 'beats'
      s.beat = BEAT_MAX
    } else if (s.screen === 'beats' && s.beat > BEAT_MIN) {
      s.beat -= 1
    }
  }

  /** Rail click-to-jump (any stop, mirrors the mock's go()). */
  function goTo(n) {
    s.screen = 'beats'
    s.beat = clampBeat(n)
    persist()
  }

  /**
   * Router door choice. D/B → prompt screen; A → in-tutorial vision upload;
   * C → manual ProductForm (the OVERLAY owns C's navigation + breadcrumb
   * side effects — state-wise C parks on 'done' like the reference skeleton).
   */
  function pick(path) {
    if (!VALID_PATHS.has(path)) return
    s.path = path
    if (path === 'D' || path === 'B') s.screen = 'prompt'
    else if (path === 'A') s.screen = 'upload'
    else s.screen = 'done'
    persist()
  }

  /** Record the product this tutorial run owns (created or adopted draft). */
  function setProduct(id) {
    s.productId = id || null
  }

  /**
   * Exit hatch (walkthrough fix 4): a pre-create path (door D prompt, A's
   * upload) silently creates an empty draft; abandoning the tutorial must not
   * leave that phantom haunting the dashboard. Called on TRUE tutorial exit
   * only (skip, done-screen exit, overlay close) — never on back-navigation
   * between tutorial screens. Deletes the run-owned product via the existing
   * products delete API (productStore.deleteProduct → DELETE /api/products/:id)
   * ONLY when a fresh fetch shows it still completely empty AND inactive;
   * anything else (data written, activated, fetch failed) keeps it — leftover
   * drafts from hook-less exits stay covered by the adopt-empty-draft rule.
   */
  async function releaseAbandonedDraft() {
    const id = s.productId
    if (!id) return false
    // Resolved here, not at setup: the hatch is the only product-store touch
    // in this composable, and it only runs when a draft exists.
    const productStore = useProductStore()
    let row
    try {
      row = await productStore.fetchProductById(id)
    } catch {
      return false // can't verify emptiness — keep the draft
    }
    // FE-9566: this also required `!row.is_active`, written when is_active meant
    // "THE active product". FE-9524/D1 redefined it as "shown as a tab", and
    // create_product sets it True for every product — including the nameless
    // draft this hatch exists to clean up — so the check skipped every draft it
    // was written for and each abandoned run leaked a product permanently.
    // isDraftUntouched is what actually protects the user's data: it keeps
    // anything named, described, or written to, whether shown or hidden.
    if (!row || !isDraftUntouched(row)) return false
    try {
      await productStore.deleteProduct(id)
    } catch {
      return false
    }
    s.productId = null
    return true
  }

  /** B-path hand-off: the interview produced a vision document → upload it. */
  function goToUpload() {
    s.screen = 'upload'
  }

  /** Agent-done / analysis-complete signal → review the proposed product. */
  function goToReview() {
    s.screen = 'review'
  }

  /** Review accepted (product activated) → done screen. */
  function finishToDone() {
    s.screen = 'done'
    persist()
    markComplete()
  }

  return {
    s,
    railStop,
    showBack,
    showNext,
    nextLabel,
    next,
    back,
    goTo,
    pick,
    setProduct,
    releaseAbandonedDraft,
    goToUpload,
    goToReview,
    finishToDone,
    markComplete,
  }
}
