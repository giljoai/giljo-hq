<template>
  <v-container>
    <!-- Page Header -->
    <h1 class="text-headline-large mb-2">Tools</h1>
    <p class="text-body-large mb-4 settings-subtitle">Manage connections, tune agents, and configure context</p>

    <!-- Settings Pills -->
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
        :class="{ 'pill-toggle--active': activeTab === 'startup' }"
        data-testid="startup-settings-tab"
        @click="activeTab = 'startup'"
      >
        <v-icon size="16" class="pill-toggle-icon">mdi-rocket-launch</v-icon>
        Startup
      </button>
    </div>

    <!-- Tab Content -->
    <div class="pill-tabs-content">
      <v-window v-model="activeTab" :touch="false" :reverse="false" class="global-tabs-window main-window-tabs">
      <!-- Context Settings -->
      <v-window-item value="context" eager>
        <ContextPriorityConfig :git-integration-enabled="gitEnabled" />
      </v-window-item>

      <!-- Agents -->
      <v-window-item value="agents">
        <!-- FE-9555: the ONE account default for the staging
             execution-mode question. It belongs on THIS tab, not with the
             notification/monitoring knobs: the headless EXECUTION_MODE_REQUIRED
             refusal tells the user in so many words to set it under Tools ->
             Agents, so anywhere else makes the product's own instruction wrong. -->
        <!-- FE-9555 (operator direction 2026-09-04): the account-wide agent policy
             controls grouped under one heading, ABOVE the template roster. The
             execution-mode default and the two orchestration switches all answer
             "how do agents behave", which the template roster below does not --
             OrchestrationToggles was only ever inside TemplateManager because that
             tab had room, as its own docstring says. Heading mirrors Agent Template
             Manager's own title + help-tooltip pattern so the two read as peers. -->
        <div class="tab-header mb-4 d-flex align-center">
          <h2 class="text-title-large">Agent Behaviour Settings</h2>
          <v-tooltip location="bottom" max-width="360">
            <template #activator="{ props: behaviourTipProps }">
              <v-icon v-bind="behaviourTipProps" size="small" class="ml-2" color="medium-emphasis"
                >mdi-help-circle-outline</v-icon
              >
            </template>
            <span>Settings that modify how agents operate in the application</span>
          </v-tooltip>
        </div>
        <ExecutionModeDefaultSelect />
        <!-- FE-9553: relocated out of Notifications. These tune how agents
             behave, not how notifications display, and this is the group for
             exactly that class of control. -->
        <AgentTimingSettings class="mb-4" />
        <OrchestrationToggles class="mb-6" />

        <TemplateManager />
      </v-window-item>

      <!-- Setup Settings -->
      <v-window-item value="startup">
        <div class="tab-header mb-4">
          <h2 class="text-title-large">Startup</h2>
          <p class="text-body-medium text-muted-a11y mt-1">Setup wizard and getting started</p>
        </div>
        <div class="startup-cards" data-test="startup-settings">
          <div
            class="startup-card smooth-border"
            style="--card-accent: var(--color-accent-primary)"
            @click="router.push({ path: '/home', query: { openSetup: 'true' } })"
          >
            <div class="startup-card-icon" style="background: rgba(255,195,0,0.1); color: var(--color-accent-primary)">
              <v-icon size="20">mdi-rocket-launch</v-icon>
            </div>
            <div class="startup-card-title">Setup Wizard</div>
            <div class="startup-card-desc">Connect AI coding tools, install skills, and configure {{ productName }}.</div>
          </div>
          <div
            class="startup-card smooth-border"
            style="--card-accent: var(--agent-documenter-primary)"
            @click="router.push({ path: '/home', query: { openGuide: 'true' } })"
          >
            <div class="startup-card-icon" style="background: rgba(94,196,142,0.12); color: var(--agent-documenter-primary)">
              <v-icon size="20">mdi-book-open-variant</v-icon>
            </div>
            <div class="startup-card-title">Learning</div>
            <div class="startup-card-desc">Understand products, projects, agents, memory, and slash commands.</div>
          </div>
          <div
            v-if="isCe"
            class="startup-card smooth-border"
            style="--card-accent: var(--agent-implementer-primary)"
            @click="showCertModal = true"
          >
            <div class="startup-card-icon" style="background: var(--agent-implementer-tinted); color: var(--agent-implementer-primary)">
              <v-icon size="20">mdi-certificate</v-icon>
            </div>
            <div class="startup-card-title">Certificate Trust</div>
            <div class="startup-card-desc">Trust the HTTPS certificate your server uses so AI coding tools can connect.</div>
          </div>
        </div>
      </v-window-item>

      <!-- Notification Settings — FE-9553: four cards, one per surface.
           Each card is its own component: this file is at the 800-line
           guardrail, and the model reads better as four named surfaces than as
           one wall of controls. Order follows the record: the surface that asks
           you for something first, the medium that delivers it second, feedback
           third, the archive last. -->
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

      <!-- Connect (formerly Integrations + API Keys folded in as Credentials) -->
      <v-window-item value="connect">
        <div class="tab-header mb-4">
          <h2 class="text-title-large">Connect</h2>
          <p class="text-body-medium text-muted-a11y mt-1">Connect external tools and services to your GiljoAI workspace</p>
        </div>

        <!-- AI-tool connect surface — C2 tool directory (FE-9204). Shared connect
             card with the setup wizard; replaces the old MCP + generic-MCP cards. -->
        <ToolsConnectDirectory class="mb-5" />

        <!-- Other integrations (non-AI-tool): export, Serena, Git. -->
        <div class="connect-grid mb-5">
          <AgentExport />
          <SerenaIntegrationCard
            :enabled="serenaEnabled"
            :loading="toggling"
            @update:enabled="toggleSerena"
          />
          <GitIntegrationCard
            :enabled="gitEnabled"
            :loading="togglingGit"
            @update:enabled="toggleGit"
          />

          <!-- FE-9339: the symptom is "my tool cannot connect", so this is where the
               user looks. Same modal the Startup card opens — that card stays, this is
               a second door, not a move. CE only: a hosted tenant has no certificate
               of its own to trust. -->
          <div
            v-if="isCe"
            class="intg-line smooth-border"
            style="--card-accent: var(--agent-implementer-primary)"
            data-testid="cert-trust-line"
          >
            <div
              class="intg-line-icon intg-line-icon--link"
              style="background: var(--agent-implementer-tinted); color: var(--agent-implementer-primary)"
              title="Open the certificate trust steps"
              @click="showCertModal = true"
            >
              <v-icon size="22">mdi-certificate</v-icon>
            </div>

            <div class="intg-line-main">
              <div class="intg-line-title-row">
                <span class="intg-line-title">Certificate Trust</span>
                <v-tooltip location="top" max-width="400">
                  <template #activator="{ props }">
                    <v-icon v-bind="props" size="small" style="color: var(--text-muted)">mdi-help-circle-outline</v-icon>
                  </template>
                  <div>
                    <strong>One-time setup for servers running HTTPS</strong>
                    <p class="mt-2 mb-0">
                      Command-line AI tools built on Node (Claude Code, Codex CLI, Gemini CLI)
                      do not read your operating system&rsquo;s trust store, so they refuse a
                      private or self-signed certificate even after your browser has accepted it.
                    </p>
                    <p class="mt-2 mb-0 text-body-small">
                      The steps cover downloading the certificate, installing it, and pointing
                      Node at it. Skip them if your server runs over plain HTTP.
                    </p>
                  </div>
                </v-tooltip>
              </div>
              <div class="intg-line-sub">AI tool refusing to connect over HTTPS? Trust your server&rsquo;s certificate.</div>
            </div>

            <div class="intg-line-action">
              <v-btn
                color="primary"
                variant="outlined"
                size="small"
                class="intg-toggle-pill"
                data-testid="cert-trust-open"
                @click="showCertModal = true"
              >
                <v-icon start size="16">mdi-open-in-new</v-icon>
                Open
              </v-btn>
            </div>
          </div>
        </div>

        <!-- Credentials (compact section, formerly the "API Keys" peer tab) -->
        <div class="credentials-section">
          <ApiKeyManager />
        </div>
      </v-window-item>
    </v-window>

    <!-- FE-9339: mounted at container level, not inside the Startup tab. VWindowItem
         renders its slot lazily, and Connect is the default tab — a modal parked
         inside a tab the user has never opened is simply not in the DOM, so the
         Connect entry point would have opened nothing. One instance, both doors. -->
    <CertTrustModal
      v-model="showCertModal"
      @continue="recordCertTrustDismissal"
    />
    </div>

  </v-container>
</template>

<script setup>
import { ref, provide, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useWebSocketStore } from '@/stores/websocket'
import TemplateManager from '@/components/TemplateManager.vue'
import ApiKeyManager from '@/components/ApiKeyManager.vue'
import { PRODUCT_NAME } from '@/branding'

const productName = PRODUCT_NAME
import AgentExport from '@/components/AgentExport.vue'
import ContextPriorityConfig from '@/components/settings/ContextPriorityConfig.vue'
import ToolsConnectDirectory from '@/components/tools/ToolsConnectDirectory.vue'
import SerenaIntegrationCard from '@/components/settings/integrations/SerenaIntegrationCard.vue'
import GitIntegrationCard from '@/components/settings/integrations/GitIntegrationCard.vue'
import setupService from '@/services/setupService'
import { isCeModeValue } from '@/composables/useGiljoMode'
import CertTrustModal from '@/components/setup/CertTrustModal.vue'
import { recordCertTrustDismissal } from '@/utils/certTrustPreference'
import AgentTimingSettings from '@/components/settings/AgentTimingSettings.vue'
import BannerPreferencesCard from '@/components/settings/BannerPreferencesCard.vue'
import BellPreferencesCard from '@/components/settings/BellPreferencesCard.vue'
import PopoutPreferencesCard from '@/components/settings/PopoutPreferencesCard.vue'
import ToastPreferencesCard from '@/components/settings/ToastPreferencesCard.vue'
import ExecutionModeDefaultSelect from '@/components/settings/ExecutionModeDefaultSelect.vue'
import OrchestrationToggles from '@/components/templates/OrchestrationToggles.vue'
// Stores and Theme
const router = useRouter()

// WebSocket for real-time Git integration updates
const { on, off } = useWebSocketStore()

// State
const activeTab = ref('connect')

// Map legacy tab values to current ones (keep deep-links working after FE-0023 IA reshuffle).
function normalizeTab(tab) {
  if (!tab) return null
  if (tab === 'general') return 'startup'
  if (tab === 'integrations' || tab === 'api-keys') return 'connect'
  return tab
}
const isCe = ref(false)
const showCertModal = ref(false)
const serenaEnabled = ref(false)
const toggling = ref(false)

// Git Integration state (system-level like Serena)
// This state is shared with ContextPriorityConfig via props
const gitEnabled = ref(false)

// Handover 0335: Provide template export event data to child components
// This allows TemplateManager to receive export events even when not actively mounted
const templateExportEvent = ref(null)
provide('templateExportEvent', templateExportEvent)
const togglingGit = ref(false)

// Methods
async function loadEditionMode() {
  try {
    const status = await setupService.checkEnhancedStatus()
    isCe.value = isCeModeValue(status?.mode)
  } catch {
    isCe.value = false
  }
}

// Serena MCP Methods
async function checkSerenaStatus() {
  try {
    const status = await setupService.getSerenaStatus()
    serenaEnabled.value = status.enabled || false
  } catch (error) {
    console.error('[USER SETTINGS] Failed to check Serena status:', error)
    serenaEnabled.value = false
  }
}

async function toggleSerena(enabled) {
  toggling.value = true
  try {
    const result = await setupService.toggleSerena(enabled)
    if (result.success) {
      serenaEnabled.value = result.enabled
    } else {
      // Revert on failure
      serenaEnabled.value = !enabled
      console.error('[USER SETTINGS] Failed to toggle Serena:', result.message)
    }
  } catch (error) {
    console.error('[USER SETTINGS] Error toggling Serena:', error)
    // Revert on error
    serenaEnabled.value = !enabled
  } finally {
    toggling.value = false
  }
}

// Lifecycle
onMounted(async () => {
  // Check for tab parameter in query string
  const route = router.currentRoute.value

  if (route.query.tab) {
    const normalized = normalizeTab(route.query.tab)
    if (normalized) activeTab.value = normalized
  }

  // Check Serena MCP status
  await checkSerenaStatus()
  await loadEditionMode()

  // FE-9553: the notification and agent-timing loads that used to live here
  // moved into the cards that own those controls. They were unguarded awaits in
  // this hook, so either one failing aborted every load after it -- including
  // loadGitSettings below, which has nothing to do with notifications.

  // Load git integration settings (system-level)
  await loadGitSettings()

  // Listen for real-time Git integration changes via WebSocket
  // This listener is at parent level to ensure it captures events even when
  // ContextPriorityConfig tab is not actively mounted
  on('product:git:settings:changed', handleGitIntegrationUpdate)

  // Handover 0335: Listen for template export events at parent level
  // This ensures events are captured even when TemplateManager tab is not active
  on('template:exported', handleTemplateExportEvent)

})

watch(activeTab, (newTab) => {
  // Replace (don't push) so browser back button returns to the previous PAGE,
  // not through every intermediate tab click within ToolsView.
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
  // Clean up WebSocket listeners to prevent memory leaks
  off('product:git:settings:changed', handleGitIntegrationUpdate)
  off('template:exported', handleTemplateExportEvent) // Handover 0335
})

// Git Integration Functions (system-level like Serena)
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
    // Revert on error
    gitEnabled.value = !enabled
  } finally {
    togglingGit.value = false
  }
}


/**
 * Handle real-time Git integration updates from WebSocket
 * This handler is at parent level to ensure it fires regardless of
 * which tab is currently active
 * @param {Object} data - WebSocket event data
 * @param {string} data.product_id - Product ID
 * @param {Object} data.settings - Git integration settings
 * @param {boolean} data.settings.enabled - Whether git integration is enabled
 */
function handleGitIntegrationUpdate(data) {
  if (!data || !data.settings) {
    console.warn('[USER SETTINGS] Received invalid git integration update:', data)
    return
  }

  const newState = data.settings.enabled || false
  gitEnabled.value = newState
}


/**
 * Handover 0335: Handle template export WebSocket events
 * This handler is at parent level to ensure it fires regardless of
 * which tab is currently active. The event data is provided to TemplateManager
 * via Vue's provide/inject system.
 *
 * @param {Object} data - WebSocket event data (already normalized by websocket store)
 * @param {string} data.tenant_key - Multi-tenant isolation key
 * @param {string[]} data.template_ids - List of exported template UUIDs
 * @param {string} data.export_type - Export type (manual_zip, personal_agents, product_agents)
 * @param {string} data.exported_at - ISO timestamp of export
 */
function handleTemplateExportEvent(data) {
  if (!data || !data.template_ids || !data.exported_at) {
    console.warn('[USER SETTINGS] Invalid template export event - missing required fields:', data)
    return
  }

  // Update the provided ref so TemplateManager can react to it
  // Include a unique ID to ensure Vue detects the change even if same templates
  templateExportEvent.value = {
    ...data,
    _eventId: Date.now(), // Force reactivity
  }
}

</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
/* FE-9339: the Certificate Trust line is authored inline in this view rather than as
   a component, so it needs the shared line-card styles its three grid siblings pull
   in through their own scoped blocks. No new card CSS. */
@use '../styles/intg-card';
.settings-subtitle {
  color: var(--text-muted);
}

.settings-card {
  background: $elevation-raised;
  border-radius: $border-radius-rounded;
}

/* Startup quick-launch cards (mirrors Home page .quick-card) */
.startup-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.startup-card {
  background: rgb(var(--v-theme-surface));
  border-radius: $border-radius-rounded;
  padding: 20px;
  cursor: pointer;
  transition: all $transition-normal;
  position: relative;
  overflow: hidden;
}

.startup-card:hover {
  transform: translateY(-3px);
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255,255,255,0.10)), 0 10px 20px -6px rgba(0,0,0,0.25);
}

.startup-card::before {
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

.startup-card:hover::before {
  opacity: 1;
}

.startup-card-icon {
  width: 40px;
  height: 40px;
  border-radius: $border-radius-default;
  display: grid;
  place-items: center;
  margin-bottom: 12px;
}

.startup-card-title {
  font-size: 0.92rem;
  font-weight: 600;
  margin-bottom: 5px;
}

.startup-card-desc {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.4;
}

/* FE-9536: same tablet-band gap as WelcomeQuickGrid's .quick-grid (this
   mirrors it, per the comment above) -- add the missing 2-col step. */
@media (max-width: $breakpoint-tablet) {
  .startup-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: $breakpoint-mobile) {
  .startup-cards {
    grid-template-columns: 1fr;
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

.startup-help-icon {
  cursor: pointer;
  opacity: 0.7;
  transition: opacity $transition-normal ease;
}

.startup-help-icon:hover {
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
