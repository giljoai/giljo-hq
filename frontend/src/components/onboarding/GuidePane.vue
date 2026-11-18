<template>
  <v-navigation-drawer
    v-if="guide.visible"
    id="guide-pane"
    :model-value="drawerOpen"
    location="right"
    :rail="railMode"
    :permanent="!isMobile"
    :temporary="isMobile"
    :mobile="false"
    :width="320"
    :rail-width="56"
    color="surface"
    class="guide-pane"
    data-testid="guide-pane"
    :aria-label="TEXT.title"
    @update:model-value="onDrawerModel"
  >
    <nav v-if="railMode" class="gp-rail" :aria-label="TEXT.title">
      <button
        type="button"
        class="gp-rail-open"
        data-testid="guide-pane-unfold"
        :aria-label="TEXT.unfold"
        @click="guide.setFolded(false)"
      >
        <v-icon size="18" icon="mdi-chevron-left" />
      </button>
      <button
        v-for="r in rows"
        :key="r.n"
        type="button"
        class="gp-dot"
        :class="[`gp-dot--${r.state}`, { 'gp-dot--current': r.current }]"
        :data-testid="`guide-dot-${r.n}`"
        :data-state="r.state"
        :aria-label="TEXT.dot(r.n, r.title, r.state, r.current)"
        @click="guide.setFolded(false)"
      >
        <v-icon v-if="r.state === 'done'" size="14" icon="mdi-check" />
        <template v-else>{{ r.n }}</template>
      </button>
    </nav>

    <div v-else class="gp-open">
      <header class="gp-head">
        <div class="gp-head-text">
          <h2 class="gp-title">{{ TEXT.title }}</h2>
          <span class="gp-count" data-testid="guide-pane-count">{{
            TEXT.count(startList.doneCount, startList.stepCount)
          }}</span>
        </div>
        <button
          v-if="!isMobile"
          type="button"
          class="gp-icon-btn"
          data-testid="guide-pane-fold"
          :aria-label="TEXT.fold"
          @click="guide.setFolded(true)"
        >
          <v-icon size="18" icon="mdi-chevron-right" />
        </button>
        <button
          type="button"
          class="gp-icon-btn"
          data-testid="guide-pane-close"
          :aria-label="TEXT.close"
          @click="guide.close()"
        >
          <v-icon size="18" icon="mdi-close" />
        </button>
      </header>

      <div v-if="guide.finished" class="gp-finished" data-testid="guide-pane-finished">
        <p class="gp-finished-line" data-testid="guide-pane-finished-line">{{ TEXT.finished }}</p>
        <p class="gp-finished-line gp-finished-line--soft" data-testid="guide-pane-finished-again">
          {{ TEXT.finishedAgain }}
        </p>
        <button type="button" class="gp-btn" data-testid="guide-pane-finished-close" @click="guide.close()">
          {{ TEXT.finishedClose }}
        </button>
      </div>

      <ol class="gp-rows">
        <li
          v-for="r in rows"
          :key="r.n"
          class="gp-row"
          :class="[`gp-row--${r.state}`, { 'gp-row--current': r.current }]"
          :data-testid="`guide-row-${r.n}`"
          :data-state="r.state"
          :data-nudged="guide.nudgedRow === r.n ? 'true' : 'false'"
        >
          <span class="gp-node" aria-hidden="true">
            <v-icon v-if="r.state === 'done'" size="14" icon="mdi-check" />
            <template v-else>{{ r.n }}</template>
          </span>
          <div class="gp-main">
            <div class="gp-title-row">
              <span class="gp-row-title">{{ r.title }}</span>
            </div>
            <div v-if="r.line || nudged(r)" class="gp-line" :data-testid="`guide-row-${r.n}-line`">{{ lineOf(r) }}</div>
            <div
              v-if="nudged(r) && !isHelp(r)"
              class="gp-line"
              :data-testid="`guide-row-${r.n}-nudge`"
            >
              {{ TEXT.nudge }}
            </div>
            <span
              v-if="r.picture"
              class="guide-btn-picture"
              :class="`guide-btn-picture--${r.picture}`"
              :data-testid="`guide-row-${r.n}-picture`"
              aria-hidden="true"
            >
              <v-icon v-if="PICTURES[r.picture].icon" size="14" :icon="PICTURES[r.picture].icon" />
              <template v-if="PICTURES[r.picture].label">{{ PICTURES[r.picture].label }}</template>
            </span>
            <div class="gp-actions" :data-testid="`guide-row-${r.n}-buttons`">
              <button
                v-for="a in r.actions"
                :key="a.id"
                type="button"
                class="gp-btn"
                :class="{
                  'gp-btn--primary': r.state === 'current',
                  'gp-btn--copied': a.id === 'copy' && copied,
                }"
                :data-testid="actionTestId(r, a)"
                :disabled="r.needsProduct"
                @click="runAction(r, a)"
              >
                <v-icon v-if="a.id === 'copy' && copied" size="14" icon="mdi-check" />
                {{ a.id === 'copy' && copied ? TEXT.copied : a.label }}
              </button>
              <button
                type="button"
                class="gp-btn gp-btn--watch"
                :class="{ 'gp-btn--quiet': r.state === 'done', 'next-press-pulse': nudged(r) }"
                :data-testid="`guide-row-${r.n}-play`"
                :aria-label="TEXT.watch(r.video.title, r.videoLength)"
                @click="playVideo(r)"
              >
                <v-icon size="16" icon="mdi-play-circle-outline" />
                {{ TEXT.watchLink(r.videoLength) }}
              </button>
            </div>
            <div
              v-if="r.n === 4 && r.actions.length && r.needsProduct"
              class="gp-line"
              data-testid="guide-row-4-needs-product"
            >
              {{ r.needsProductLine }}
            </div>
            <div
              v-if="r.n === 4 && r.actions.length"
              class="gp-line"
              data-testid="guide-row-4-ask"
            >
              {{ r.extraLine }}
            </div>
            <button
              v-if="r.goToProjects && !onProjectsPage"
              type="button"
              class="gp-link"
              :data-testid="`guide-row-${r.n}-goto`"
              @click="goToProjects"
            >
              {{ TEXT.goToProjects }}
            </button>
            <button
              v-if="r.showCard && !onImplementationBoard"
              type="button"
              class="gp-link"
              :data-testid="`guide-row-${r.n}-card`"
              @click="showCard"
            >
              {{ TEXT.showCard }}
            </button>
            <div
              v-if="r.n === 2"
              class="gp-sr"
              aria-live="polite"
              data-testid="guide-row-2-live"
            >
              {{ copied ? TEXT.copied : '' }}
            </div>
          </div>
        </li>
      </ol>
    </div>
  </v-navigation-drawer>

  <button
    v-if="guide.visible && isMobile && !mobileOpen"
    type="button"
    class="gp-mobile-open smooth-border"
    data-testid="guide-pane-mobile-open"
    @click="mobileOpen = true"
  >
    <v-icon size="18" icon="mdi-format-list-checks" />
    {{ TEXT.openMobile }}
    <span class="gp-mobile-count">{{ TEXT.count(startList.doneCount, startList.stepCount) }}</span>
  </button>

  <StartProductDialog v-model="productDialogOpen" />
  <IntroVideoDialog :model-value="videoOpen" :video="activeVideo" @close="videoOpen = false" />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import IntroVideoDialog from '@/components/onboarding/IntroVideoDialog.vue'
import StartProductDialog from '@/components/onboarding/StartProductDialog.vue'
import { useSetupRequestCopy } from '@/composables/useSetupRequestCopy'
import { PROJECT_TEMPLATES } from '@/composables/projectTemplates'
import { useStarterProject } from '@/composables/useStarterProject'
import { buildGuideRows, GUIDE_TEXT as TEXT, GUIDE_VIDEOS } from '@/content/onboarding/guide'
import { useGuideStore } from '@/stores/guide'
import { useStartListStore } from '@/stores/startList'

const SMALL_SCREEN = 1024
const PANE_WIDTH = 320
const RAIL_WIDTH = 56
const PROJECT_PAGES = ['Projects', 'JobsViewport']
const PICTURES = Object.freeze({
  play: { icon: 'mdi-play', label: '' },
  implement: { icon: 'mdi-play', label: 'Implement' },
  review: { icon: '', label: 'Review project' },
})
const STARTERS = { import: 'existing_product_bootstrap', bootstrap: 'new_product_bootstrap' }

const router = useRouter()
const route = useRoute()
const guide = useGuideStore()
const startList = useStartListStore()
const { createFromTemplate } = useStarterProject()

const rows = computed(() => (startList.rows ? buildGuideRows(startList.rows) : []))

const width = ref(window.innerWidth)
const isMobile = computed(() => width.value <= SMALL_SCREEN)
const mobileOpen = ref(false)
const railMode = computed(() => !isMobile.value && guide.folded)
const drawerOpen = computed(() => (isMobile.value ? mobileOpen.value : true))

const onProjectsPage = computed(() => PROJECT_PAGES.includes(route?.name))
const onImplementationBoard = computed(
  () => route?.name === 'JobsViewport' && route?.query?.side === 'implementation',
)

const nudged = (row) => guide.nudgedRow === row.n
const isHelp = (row) => row.state === 'current' || row.state === 'todo'
const lineOf = (row) => (nudged(row) && isHelp(row) ? TEXT.nudge : row.line)

watchEffect(() => {
  const takesRoom = guide.visible && !isMobile.value
  guide.setReservedWidth(takesRoom ? (guide.folded ? RAIL_WIDTH : PANE_WIDTH) : 0)
})

function onResize() {
  width.value = window.innerWidth
}
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  guide.setReservedWidth(0)
})

function onDrawerModel(open) {
  if (isMobile.value) mobileOpen.value = open
}

const productDialogOpen = ref(false)
const videoOpen = ref(false)
const activeVideo = ref(GUIDE_VIDEOS[0])

function playVideo(row) {
  guide.endNudge(row.n)
  activeVideo.value = row.video
  videoOpen.value = true
}

const { copied, copyRequest } = useSetupRequestCopy()

function goToProjects() {
  router.push({ name: 'Projects' })
}

function showCard() {
  router.push({ name: 'JobsViewport', query: { side: 'implementation' } })
}

function actionTestId(row, action) {
  return row.n === 4 ? `guide-row-4-${action.id}` : `guide-row-${row.n}-action`
}

function runAction(_row, action) {
  if (action.id === 'connect') router.push({ path: '/home', query: { openSetup: 'true' } })
  else if (action.id === 'copy') copyRequest()
  else if (action.id === 'product') productDialogOpen.value = true
  else if (STARTERS[action.id]) {
    createFromTemplate(PROJECT_TEMPLATES.find((t) => t.id === STARTERS[action.id]))
  }
}
</script>

<style scoped lang="scss">
@use '@/styles/design-tokens' as *;

.gp-open {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 16px 14px 20px;
}

.gp-head {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 12px;
}

.gp-head-text {
  flex: 1;
  min-width: 0;
}

.gp-title {
  font-size: 1rem;
  font-weight: 700;
  margin: 0;
  color: var(--color-text-primary);
}

.gp-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  color: var(--text-secondary);
}

.gp-icon-btn,
.gp-rail-open {
  display: inline-grid;
  place-items: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: none;
  border: 0;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
}

.gp-icon-btn:hover,
.gp-rail-open:hover {
  color: var(--color-text-primary);
}

.gp-icon-btn:focus-visible,
.gp-rail-open:focus-visible,
.gp-link:focus-visible,
.gp-dot:focus-visible,
.gp-btn:focus-visible,
.gp-mobile-open:focus-visible {
  outline: 2px solid $color-brand-yellow;
  outline-offset: 2px;
}

.gp-finished {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  margin: 0 0 12px;
  padding: 12px;
  border-radius: 8px;
  background: rgba($color-status-complete, 0.12);
}

.gp-finished-line {
  margin: 0;
  font-weight: 600;
  color: $color-status-complete;
}

.gp-finished-line--soft {
  font-weight: 400;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.gp-rows {
  list-style: none;
  margin: 0;
  padding: 0;
}

.gp-row {
  display: flex;
  gap: 10px;
  padding: 10px 6px;
  min-width: 0;
  border-radius: 12px;
}

.gp-row + .gp-row {
  border-top: 1px solid $color-border-tertiary;
}

.gp-row--current {
  background: rgba($color-brand-yellow, 0.07);
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.35);
  border-top-color: transparent;
}

.gp-node,
.gp-dot {
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  font-size: 0.74rem;
  font-weight: 600;
  color: var(--text-secondary);
  box-shadow: inset 0 0 0 1px $color-border-primary;
}

.gp-node {
  border-radius: 50%;
}

.gp-dot {
  border-radius: $border-radius-default;
}

.gp-row--current .gp-node,
.gp-dot--current {
  color: rgb(var(--v-theme-warning));
  box-shadow: inset 0 0 0 1.5px rgb(var(--v-theme-warning));
}

.gp-row--done .gp-node,
.gp-dot--done {
  color: $color-status-complete;
  box-shadow: inset 0 0 0 1.5px $color-status-complete;
}

.gp-main {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.gp-title-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.gp-row-title {
  flex: 1;
  font-weight: 600;
  font-size: 0.86rem;
  color: var(--color-text-primary);
}

.gp-line {
  margin-top: 2px;
  font-size: 0.78rem;
  color: var(--text-secondary);
}

.gp-link {
  display: block;
  margin: 6px auto 0;
  text-align: center;
  padding: 0;
  background: none;
  border: 0;
  font: inherit;
  font-size: 0.78rem;
  color: rgb(var(--v-theme-primary));
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.gp-link:hover {
  color: var(--color-text-primary);
}

.guide-btn-picture {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
  min-height: 24px;
  padding: 0 9px;
  border-radius: 8px;
  font-size: 0.72rem;
  font-weight: 600;
  line-height: 1;
  pointer-events: none;
  user-select: none;
  cursor: default;
}

.guide-btn-picture--play {
  padding: 0 6px;
  color: $color-brand-yellow;
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.6);
  width: 24px;
  justify-content: center;
}

.guide-btn-picture--implement {
  background: $color-brand-yellow;
  color: $color-on-yellow-ink;
}

.guide-btn-picture--review {
  background: $color-status-complete;
  color: $color-on-yellow-ink;
}

.gp-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}

.gp-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 8px;
  border: 0;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-text-primary);
  background: transparent;
  box-shadow: inset 0 0 0 1px $color-border-primary;
}

.gp-btn--primary {
  background: $color-brand-yellow;
  color: $color-on-yellow-ink;
  box-shadow: none;
}

.gp-btn--quiet {
  color: var(--text-muted);
  box-shadow: inset 0 0 0 1px $color-border-tertiary;
}

.gp-btn--watch {
  color: $color-brand-yellow;
  background: transparent;
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.6);
}

.gp-btn--watch:hover {
  background: rgba($color-brand-yellow, 0.1);
  box-shadow: inset 0 0 0 1px $color-brand-yellow;
}

.gp-btn--watch.gp-btn--quiet {
  color: rgba($color-brand-yellow, 0.75);
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.35);
}

.gp-btn--watch.gp-btn--quiet:hover {
  background: rgba($color-brand-yellow, 0.08);
  box-shadow: inset 0 0 0 1px rgba($color-brand-yellow, 0.6);
}

.gp-btn--copied,
.gp-btn--primary.gp-btn--copied {
  background: transparent;
  color: rgb(var(--v-theme-primary));
  box-shadow: inset 0 0 0 1.5px rgb(var(--v-theme-primary));
}

.gp-btn:disabled {
  cursor: default;
  color: var(--text-muted);
  background: transparent;
  box-shadow: inset 0 0 0 1px $color-border-tertiary;
}

.gp-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 12px 0;
}

.gp-dot {
  background: none;
  border: 0;
  cursor: pointer;
}

.gp-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.gp-mobile-open {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 1005;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border: 0;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-text-primary);
  background: rgb(var(--v-theme-surface));
}

.gp-mobile-count {
  font-family: 'IBM Plex Mono', monospace;
  color: var(--text-secondary);
}
</style>
