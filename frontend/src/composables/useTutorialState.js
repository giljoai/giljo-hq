import { reactive, computed } from 'vue'
import { useProductStore } from '@/stores/products'
import { useUserStore } from '@/stores/user'

export const TUTORIAL_STOPS = Object.freeze([
  'How it works',
  'Product & crew',
  'Missions',
  '360 Memory',
  'The destination',
  'Get started',
])

const BREADCRUMB_KEY = 'giljo_tutorial_activate_breadcrumb'

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

const hasText = (value) => typeof value === 'string' && value.trim().length > 0

function sectionHasContent(section) {
  if (!section || typeof section !== 'object') return false
  return Object.values(section).some(
    (value) => hasText(value) || (Array.isArray(value) && value.length > 0),
  )
}

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

  const user = userStore.currentUser
  const s = reactive({
    beat: clampBeat(user?.learning_beat ?? BEAT_MIN),
    screen: 'beats',
    path: VALID_PATHS.has(user?.router_choice) ? user.router_choice : null,
    productId: null,
  })

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
      s.screen = 'beats'
      s.beat = BEAT_MAX
    } else if (s.screen === 'beats' && s.beat > BEAT_MIN) {
      s.beat -= 1
    }
  }

  function goTo(n) {
    s.screen = 'beats'
    s.beat = clampBeat(n)
    persist()
  }

  function pick(path) {
    if (!VALID_PATHS.has(path)) return
    s.path = path
    if (path === 'D' || path === 'B') s.screen = 'prompt'
    else if (path === 'A') s.screen = 'upload'
    else s.screen = 'done'
    persist()
  }

  function setProduct(id) {
    s.productId = id || null
  }

  async function releaseAbandonedDraft() {
    const id = s.productId
    if (!id) return false
    const productStore = useProductStore()
    let row
    try {
      row = await productStore.fetchProductById(id)
    } catch {
      return false
    }
    if (!row || !isDraftUntouched(row)) return false
    try {
      await productStore.deleteProduct(id)
    } catch {
      return false
    }
    s.productId = null
    return true
  }

  function goToUpload() {
    s.screen = 'upload'
  }

  function goToReview() {
    s.screen = 'review'
  }

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
