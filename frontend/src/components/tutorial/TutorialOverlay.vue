<template>
  <Teleport to="body">
    <Transition name="overlay-fade">
      <div
        v-if="modelValue"
        class="tutorial-overlay"
        data-testid="tutorial-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="GiljoAI tour"
        @keydown.escape="handleSkip"
      >
        <!-- Backdrop — click does NOT close (parity with the setup wizard) -->
        <div class="tutorial-backdrop" />

        <div
          :class="['tutorial-panel', 'smooth-border', { 'tutorial--reduced': reducedMotion }]"
          tabindex="-1"
        >
          <TutorialRail :active-stop="railStop" @go="goTo" />

          <div class="tutorial-main">
            <div class="tutorial-content">
              <template v-if="s.screen === 'beats'">
                <TutorialBeat1 v-if="s.beat === 1" :key="`beat1-${replayKey}`" />
                <TutorialBeat2 v-else-if="s.beat === 2" :key="`beat2-${replayKey}`" />
                <TutorialBeat3 v-else-if="s.beat === 3" :key="`beat3-${replayKey}`" />
                <TutorialBeat4 v-else-if="s.beat === 4" :key="`beat4-${replayKey}`" />
                <TutorialBeat5 v-else-if="s.beat === 5" :key="`beat5-${replayKey}`" />
                <TutorialRouter v-else @pick="onPick" />
              </template>
              <TutorialPromptScreen
                v-else-if="s.screen === 'prompt'"
                :path="s.path || 'D'"
                :product-id="s.productId"
                @product-created="setProduct"
                @review="goToReview"
                @upload="goToUpload"
                @manual="goManual"
              />
              <TutorialUploadScreen
                v-else-if="s.screen === 'upload'"
                :product-id="s.productId"
                @product-created="setProduct"
                @product-invalidated="setProduct(null)"
                @review="goToReview"
                @manual="goManual"
              />
              <TutorialReviewScreen
                v-else-if="s.screen === 'review'"
                :product-id="s.productId"
                @activated="finishToDone"
              />
              <TutorialDoneScreen
                v-else-if="s.screen === 'done'"
                :router-choice="s.path"
                @close="handleSkip"
              />
            </div>

            <TutorialFooter
              :show-back="showBack"
              :show-next="showNext"
              :show-replay="s.screen === 'beats' && s.beat < 6"
              :next-label="nextLabel"
              @skip="handleSkip"
              @back="back"
              @next="next"
              @replay="replayKey++"
            />
          </div>
        </div>

        <!-- Door C is the only door that navigates away immediately — confirm
             before leaving (walkthrough fix 3). Cancel returns to the router;
             confirm proceeds exactly as before (ProductForm + breadcrumb). -->
        <BaseDialog
          v-model="showDoorCConfirm"
          type="warning"
          title="Leave the tutorial?"
          icon="mdi-pencil-outline"
          confirm-label="Open the product form"
          @confirm="confirmDoorC"
          @cancel="cancelDoorC"
        >
          <p data-testid="tutorial-doorc-confirm-text" class="mb-0">
            This opens the product form and leaves the tutorial — ready to fill it in yourself?
          </p>
        </BaseDialog>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import TutorialRail from './TutorialRail.vue'
import TutorialFooter from './TutorialFooter.vue'
import TutorialBeat1 from './beats/TutorialBeat1.vue'
import TutorialBeat2 from './beats/TutorialBeat2.vue'
import TutorialBeat3 from './beats/TutorialBeat3.vue'
import TutorialBeat4 from './beats/TutorialBeat4.vue'
import TutorialBeat5 from './beats/TutorialBeat5.vue'
import TutorialRouter from './TutorialRouter.vue'
import TutorialPromptScreen from './TutorialPromptScreen.vue'
import TutorialUploadScreen from './TutorialUploadScreen.vue'
import TutorialReviewScreen from './TutorialReviewScreen.vue'
import TutorialDoneScreen from './TutorialDoneScreen.vue'
import BaseDialog from '@/components/common/BaseDialog.vue'
import { armActivateBreadcrumb, useTutorialState } from '@/composables/useTutorialState'

defineProps({
  modelValue: {
    type: Boolean,
    required: true,
  },
})

const emit = defineEmits(['update:modelValue', 'dismiss'])

const router = useRouter()

const {
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
  goToUpload,
  goToReview,
  finishToDone,
  markComplete,
  releaseAbandonedDraft,
} = useTutorialState()

// Bumping the key re-mounts the current beat, restarting its CSS animations
// (the per-beat replay control — skip + replay stay always available).
const replayKey = ref(0)

// Reduced motion: swap every animation for its final frame. Evaluated once
// per mount — matches the mock's .gj-anim media-query gate, but class-driven
// so component tests can exercise it.
const reducedMotion = ref(
  typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches,
)

function close() {
  // TRUE tutorial exit (skip / done-screen exit / esc / door C confirm) —
  // fire-and-forget the abandoned-draft hatch (walkthrough fix 4). Back-nav
  // between tutorial screens never comes through here.
  releaseAbandonedDraft()
  emit('dismiss')
  emit('update:modelValue', false)
}

function handleSkip() {
  markComplete()
  close()
}

// Door C confirmation (walkthrough fix 3): every other door opens an interim
// screen with a back button; C navigates away — confirm first. pick('C') is
// deferred to confirm so a cancel leaves the state machine on the router.
const showDoorCConfirm = ref(false)

function onPick(path) {
  if (path === 'C') {
    showDoorCConfirm.value = true
    return
  }
  pick(path)
}

function cancelDoorC() {
  showDoorCConfirm.value = false
}

// Leave the tutorial for the manual form: drop the activate nudge behind, finish
// the tutorial, and open the classic ProductForm on the Products page.
function leaveForManualForm() {
  armActivateBreadcrumb()
  markComplete()
  close()
  router.push('/Products?create=true')
}

function confirmDoorC() {
  showDoorCConfirm.value = false
  // Path C: the manual form.
  pick('C')
  leaveForManualForm()
}

// FE-9320: escape hatch from either agent-driven door once it is clear no
// connected agent is coming (the door's own stalled state offers it). The
// recorded router_choice is deliberately NOT rewritten to 'C' — the user did
// pick the door they picked, and this is the same destination, not the same
// choice.
function goManual() {
  leaveForManualForm()
}
</script>

<style scoped lang="scss">
@use '../../styles/design-tokens' as *;

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

.tutorial-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.tutorial-backdrop {
  position: absolute;
  inset: 0;
  background: rgba($color-background-primary, 0.85);
}

.tutorial-panel {
  position: relative;
  width: min(1080px, 96vw);
  height: min(660px, calc(100vh - 48px));
  background: $color-background-primary;
  border-radius: $border-radius-rounded;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.1), 0 32px 96px rgba(0, 0, 0, 0.6);
  display: flex;
  overflow: hidden;
}

.tutorial-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.tutorial-content {
  flex: 1;
  padding: 34px 44px 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
}

/* Per-beat "read more" deep link into /guide (proposal §3) — shared style,
   the beats themselves stay animation-only. */
.tutorial-content :deep(.beat-readmore) {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: $color-brand-yellow;
  text-decoration: none;
  white-space: nowrap;
  margin-left: 6px;

  &:hover {
    text-decoration: underline;
    text-underline-offset: 2px;
  }
}

/* Reduced motion — final frames instead of animation, both via the user's
   OS preference and via the class-driven gate above. */
@media (prefers-reduced-motion: reduce) {
  .tutorial-panel :deep(*) {
    animation: none !important;
  }
}

.tutorial--reduced :deep(*) {
  animation: none !important;
}

/* Responsive: rail stacks above content on narrow viewports */
@media (max-width: 720px) {
  .tutorial-panel {
    flex-direction: column;
    height: auto;
    max-height: calc(100vh - 48px);
    overflow-y: auto;
  }

  .tutorial-content {
    padding: 24px 20px 0;
  }
}
</style>
