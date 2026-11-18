<template>
  <v-container>
    <h1 class="text-headline-large mb-2">Tools</h1>
    <p class="text-body-large mb-4 settings-subtitle">Manage connections, tune agents, and configure context</p>

    <div class="pill-toggle-row">
      <button
        class="pill-toggle smooth-border"
        :class="{ 'pill-toggle--active': activeTab === 'connect' }"
        data-testid="connect-settings-tab"
        @click="activeTab = 'connect'"
      >
        <v-icon size="16" class="pill-toggle-icon">mdi-puzzle</v-icon>
        Connect
      </button>
      <button
        class="pill-toggle smooth-border"
        :class="{ 'pill-toggle--active': activeTab === 'agents' }"
        data-testid="agent-templates-settings-tab"
        @click="activeTab = 'agents'"
      >
        <v-img :src="activeTab === 'agents' ? '/icons/Giljo_YW_Face.svg' : '/icons/Giljo_Inactive_Dark.svg'" width="16" height="16" class="pill-toggle-icon" />
        Agents
      </button>
      <button
        class="pill-toggle smooth-border"
        :class="{ 'pill-toggle--active': activeTab === 'context' }"
        data-testid="context-settings-tab"
        @click="activeTab = 'context'"
      >
        <v-icon size="16" class="pill-toggle-icon">mdi-layers-triple</v-icon>
        Context
      </button>
      <button
        class="pill-toggle smooth-border"
        :class="{ 'pill-toggle--active': activeTab === 'notifications' }"
        @click="activeTab = 'notifications'"
      >
        <v-icon size="16" class="pill-toggle-icon">mdi-bell</v-icon>
        Notifications
      </button>
      <button
        class="pill-toggle smooth-border"
        :class="{ 'pill-toggle--active': activeTab === 'learning' }"
        data-testid="learning-settings-tab"
        @click="activeTab = 'learning'"
      >
        <v-icon size="16" class="pill-toggle-icon">mdi-school-outline</v-icon>
        Learning
      </button>
    </div>

    <div class="pill-tabs-content">
      <v-window v-model="activeTab" :touch="false" :reverse="false" class="global-tabs-window main-window-tabs">
      <v-window-item value="context" eager>
        <ContextPriorityConfig :git-integration-enabled="gitEnabled" />
      </v-window-item>

      <v-window-item value="agents">
        <TemplateManager />
      </v-window-item>

      <v-window-item value="learning">
        <div class="tab-header mb-4">
          <h2 class="text-title-large">Learning</h2>
          <p class="text-body-medium text-muted-a11y mt-1">Guides, videos and setup help for getting going with Giljo HQ</p>
        </div>
        <div class="learning-cards" data-testid="learning-cards">
          <div
            class="learning-card smooth-border"
            role="button"
            tabindex="0"
            data-testid="learning-card-getting-started"
            style="--card-accent: var(--agent-implementer-primary)"
            @click="bringGuideBack"
            @keydown.enter.prevent="bringGuideBack"
            @keydown.space.prevent="bringGuideBack"
          >
            <div class="learning-card-icon" style="background: var(--agent-implementer-tinted); color: var(--agent-implementer-primary)">
              <v-icon size="20">mdi-format-list-checks</v-icon>
            </div>
            <div class="learning-card-title">Getting started checklist</div>
            <div class="learning-card-desc">Bring back the step-by-step checklist.</div>
            <div v-if="startList.loaded" class="learning-card-count" data-testid="learning-card-count">
              {{ startList.allDone ? `All ${startList.stepCount} done` : `${startList.doneCount} of ${startList.stepCount} done` }}
            </div>
            <div v-if="guideBackFailed" class="learning-card-error" role="alert" data-testid="learning-card-error">
              Could not bring the guide back. Please try again.
            </div>
          </div>
          <div
            class="learning-card smooth-border"
            role="button"
            tabindex="0"
            data-testid="learning-card-connect"
            style="--card-accent: var(--agent-reviewer-primary)"
            @click="connectATool"
            @keydown.enter.prevent="connectATool"
            @keydown.space.prevent="connectATool"
          >
            <div class="learning-card-icon" style="background: var(--agent-reviewer-tinted); color: var(--agent-reviewer-primary)">
              <v-icon size="20">mdi-connection</v-icon>
            </div>
            <div class="learning-card-title">Connect a tool</div>
            <div class="learning-card-desc">Add another AI tool to Giljo HQ.</div>
          </div>
          <div
            class="learning-card smooth-border"
            role="button"
            tabindex="0"
            data-testid="learning-card-videos"
            style="--card-accent: var(--agent-orchestrator-primary)"
            @click="videosOpen = true"
            @keydown.enter.prevent="videosOpen = true"
            @keydown.space.prevent="videosOpen = true"
          >
            <div class="learning-card-icon" style="background: var(--agent-orchestrator-tinted); color: var(--agent-orchestrator-primary)">
              <v-icon size="20">mdi-play-circle-outline</v-icon>
            </div>
            <div class="learning-card-title">Videos and animations</div>
            <div class="learning-card-desc">The start video, the lessons and the animated tour.</div>
          </div>
          <div
            class="learning-card smooth-border"
            role="link"
            tabindex="0"
            data-testid="learning-card-user-guide"
            style="--card-accent: var(--agent-documenter-primary)"
            @click="router.push({ name: 'UserGuide' })"
            @keydown.enter.prevent="router.push({ name: 'UserGuide' })"
            @keydown.space.prevent="router.push({ name: 'UserGuide' })"
          >
            <div class="learning-card-icon" style="background: var(--agent-documenter-tinted); color: var(--agent-documenter-primary)">
              <v-icon size="20">mdi-book-open-variant</v-icon>
            </div>
            <div class="learning-card-title">User guide</div>
            <div class="learning-card-desc">Read the full guide to Giljo HQ.</div>
          </div>
        </div>
        <VideosLibraryDialog :model-value="videosOpen" @close="videosOpen = false" @open-tour="openTour" />
      </v-window-item>

      <v-window-item value="notifications">
        <div class="tab-header mb-4">
          <h2 class="text-title-large">Notifications</h2>
          <p class="text-body-medium text-muted-a11y mt-1">
            Each surface has one job. Choose how much of each you want.
          </p>
        </div>
        <BannerPreferencesCard class="mb-4" />
        <PopoutPreferencesCard class="mb-4" />
        <ToastPreferencesCard class="mb-4" />
        <BellPreferencesCard />
      </v-window-item>

      <v-window-item value="connect">
        <div class="tab-header mb-4">
          <h2 class="text-title-large">Connect</h2>
          <p class="text-body-medium text-muted-a11y mt-1">Connect external tools and services to your {{ productName }} workspace</p>
        </div>

        <ToolsConnectDirectory class="mb-5" />

        <div class="connect-grid mb-5">
          <AgentExport />
          <GitIntegrationCard
            :enabled="gitEnabled"
            :loading="togglingGit"
            @update:enabled="toggleGit"
          />
        </div>

        <div class="credentials-section">
          <ConnectedAppsManager class="mb-5" />
          <ApiKeyManager />
        </div>
      </v-window-item>
    </v-window>

    </div>

  </v-container>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useWebSocketStore } from '@/stores/websocket'
import TemplateManager from '@/components/TemplateManager.vue'
import ApiKeyManager from '@/components/ApiKeyManager.vue'
import ConnectedAppsManager from '@/components/ConnectedAppsManager.vue'
import { PRODUCT_NAME } from '@/branding'
import { useStartListStore } from '@/stores/startList'
import { useGuideStore } from '@/stores/guide'
import { useStartListLive } from '@/composables/useStartListLive'
import VideosLibraryDialog from '@/components/onboarding/VideosLibraryDialog.vue'

const productName = PRODUCT_NAME
import AgentExport from '@/components/AgentExport.vue'
import ContextPriorityConfig from '@/components/settings/ContextPriorityConfig.vue'
import ToolsConnectDirectory from '@/components/tools/ToolsConnectDirectory.vue'
import GitIntegrationCard from '@/components/settings/integrations/GitIntegrationCard.vue'
import setupService from '@/services/setupService'
import BannerPreferencesCard from '@/components/settings/BannerPreferencesCard.vue'
import BellPreferencesCard from '@/components/settings/BellPreferencesCard.vue'
import PopoutPreferencesCard from '@/components/settings/PopoutPreferencesCard.vue'
import ToastPreferencesCard from '@/components/settings/ToastPreferencesCard.vue'
const router = useRouter()
const startList = useStartListStore()
const guide = useGuideStore()
useStartListLive()
const videosOpen = ref(false)

const guideBackFailed = ref(false)

async function bringGuideBack() {
  guideBackFailed.value = false
  guideBackFailed.value = (await guide.turnOn()) === false
}

function connectATool() {
  router.push({ path: '/home', query: { openSetup: 'new' } })
}

function openTour() {
  router.push({ path: '/home', query: { openGuide: 'true' } })
}

const { on, off } = useWebSocketStore()

const activeTab = ref('connect')

function normalizeTab(tab) {
  if (!tab) return null
  if (tab === 'general' || tab === 'startup') return 'learning'
  if (tab === 'integrations' || tab === 'api-keys') return 'connect'
  return tab
}

const gitEnabled = ref(false)

const togglingGit = ref(false)

onMounted(async () => {
  const route = router.currentRoute.value

  if (route.query.tab) {
    const normalized = normalizeTab(route.query.tab)
    if (normalized) activeTab.value = normalized
  }



  await loadGitSettings()

  on('product:git:settings:changed', handleGitIntegrationUpdate)

})

watch(activeTab, (newTab) => {
  const currentQuery = router.currentRoute.value.query
  if (currentQuery.tab !== newTab) {
    router.replace({ query: { ...currentQuery, tab: newTab } })
  }
})

watch(
  () => router.currentRoute.value.query.tab,
  (tab) => {
    if (!tab) return
    const normalized = normalizeTab(tab)
    if (normalized) activeTab.value = normalized
  },
)

onUnmounted(() => {
  off('product:git:settings:changed', handleGitIntegrationUpdate)
})

async function loadGitSettings() {
  try {
    const settings = await setupService.getGitSettings()
    gitEnabled.value = settings.enabled || false
  } catch (error) {
    console.error('[USER SETTINGS] Failed to load git settings:', error)
    gitEnabled.value = false
  }
}

async function toggleGit(enabled) {
  togglingGit.value = true

  try {
    const result = await setupService.toggleGit(enabled)
    gitEnabled.value = result.enabled
  } catch (error) {
    console.error('[USER SETTINGS] Git toggle failed:', error)
    gitEnabled.value = !enabled
  } finally {
    togglingGit.value = false
  }
}


function handleGitIntegrationUpdate(data) {
  if (!data || !data.settings) {
    console.warn('[USER SETTINGS] Received invalid git integration update:', data)
    return
  }

  const newState = data.settings.enabled || false
  gitEnabled.value = newState
}

</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.settings-subtitle {
  color: var(--text-muted);
}

.settings-card {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
}

/* Startup quick-launch cards (mirrors Home page .quick-card) */
.learning-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.learning-card {
  background: rgb(var(--v-theme-surface));
  border-radius: $border-radius-rounded;
  padding: 20px;
  cursor: pointer;
  transition: all $transition-normal;
  position: relative;
  overflow: hidden;
}

.learning-card:hover {
  transform: translateY(-3px);
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255,255,255,0.10)), 0 10px 20px -6px rgba(0,0,0,0.25);
}

.learning-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--card-accent, rgba(255,255,255,0.10));
  opacity: 0;
  transition: opacity $transition-normal;
}

.learning-card:hover::before {
  opacity: 1;
}

.learning-card-icon {
  width: 40px;
  height: 40px;
  border-radius: $border-radius-default;
  display: grid;
  place-items: center;
  margin-bottom: 12px;
}

.learning-card-title {
  font-size: 0.92rem;
  font-weight: 600;
  margin-bottom: 5px;
}

.learning-card-desc {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.4;
}

.learning-card-error {
  margin-top: 10px;
  font-size: 0.78rem;
  color: $color-status-error;
}

.learning-card-count {
  margin-top: 10px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  color: var(--text-secondary);
}

/* FE-9536: same tablet-band gap as WelcomeQuickGrid's .quick-grid (this
   mirrors it, per the comment above) -- add the missing 2-col step. */
@media (max-width: $breakpoint-tablet) {
  .learning-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* Integration page section labels (IBM Plex Mono uppercase) */
.integration-section-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  color: $color-text-muted;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 12px;
  margin-top: 28px;
}

.integration-section-label:first-of-type {
  margin-top: 0;
}

/* Connect cards — full-width horizontal rows, stacked vertically. */
.connect-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 1100px;
}

/* Integrations section divider should follow theme */
.integrations-divider {
  --v-theme-overlay-multiplier: 1; /* ensure visibility */
  border-color: var(--v-theme-on-surface);
  opacity: 0.3;
}

.learning-help-icon {
  cursor: pointer;
  opacity: 0.7;
  transition: opacity $transition-normal ease;
}

.learning-help-icon:hover {
  opacity: 1;
}

/* Pill toggle row */
.pill-toggle-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.pill-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: $border-radius-pill;
  padding: 8px 18px;
  font-size: 0.78rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background $transition-normal, color $transition-normal, box-shadow $transition-normal;
  background: transparent;
  color: var(--text-muted);
  border: none;
  --smooth-border-color: #{$color-pill-border};
}

.pill-toggle:hover {
  color: $color-text-hover;
}

.pill-toggle--active,
.pill-toggle--active:hover {
  background: rgba($color-brand-yellow, 0.12);
  color: $color-brand-yellow;
  box-shadow: none;
}

.pill-toggle-icon {
  flex-shrink: 0;
}

.pill-tabs-content {
  padding: 16px 0;
}

/* FE-9616: sticky toolbar. Pinned by
   ToolsView.fe9616.spec.js -- do not remove. */
.pill-tabs-content :deep(.v-window) {
  overflow: visible;
}

/* Credentials section -- compact API key manager folded under Connect tab */
.credentials-section {
  margin-top: 24px;
  padding-top: 24px;
  position: relative;
}

.credentials-section::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
}
</style>
