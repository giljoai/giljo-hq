<template>
  <div class="welcome-wrapper">
    <div class="welcome-atmosphere"></div>
    <div class="welcome-page">

      <!-- HERO -->
      <div class="hero">
        <div class="hero-mascot">
          <div class="hero-mascot-glow"></div>
          <div class="hero-mascot-inner">
            <GilMascot :size="88" :dark-eyes="false" />
          </div>
        </div>
        <h1 class="hero-greeting">{{ fullGreeting }}</h1>
        <p class="hero-subtitle">
          The context engineering platform for AI-assisted development.<br>
          <span class="hero-subtitle-dim">Define your product once — every agent starts with the full picture.</span>
        </p>
      </div>

      <!-- QUICK LAUNCH -->
      <div class="section-label">Quick Launch</div>
      <WelcomeQuickGrid
        :cards="quickCards"
        @card-click="onCardClick"
      />

      <!-- YOUR TEAM (hidden during onboarding) -->
      <WelcomeTeamSection
        v-if="onboardingComplete"
        :active-templates="activeTemplates"
        :empty-slots="emptySlots"
        :total-slots="totalSlots"
        :has-stale-agents="hasStaleAgents"
      />

      <!-- CONDITIONAL SECTION: Setup or Recent Projects (hidden during onboarding) -->
      <div v-if="!setupComplete && onboardingComplete" class="setup-cta-section">
        <div class="setup-cta smooth-border" @click="openSetupWithCertGate">
          <v-icon size="24" color="var(--color-accent-primary)">mdi-rocket-launch</v-icon>
          <div class="setup-cta-text">
            <div class="setup-cta-title">{{ setupCtaLabel }}</div>
            <div class="setup-cta-desc">Configure AI tools, manage connections, and learn the basics.</div>
          </div>
          <v-icon size="18" style="color:var(--text-muted);">mdi-chevron-right</v-icon>
        </div>
      </div>
      <div v-else-if="onboardingComplete && recentProjects.length > 0" class="recent-projects-section">
        <div class="recent-projects-panel smooth-border">
          <div class="rp-header">
            <span class="rp-title">Recent Projects</span>
            <router-link to="/Projects" class="rp-link">All Projects →</router-link>
          </div>
          <RecentProjectsList
            :projects="recentProjects"
            @review-project="handleReviewProject"
          />
        </div>
      </div>

      <!-- FOOTER -->
      <div class="page-footer">
        <span class="footer-item mono">{{ appVersion }}</span>
      </div>
    </div>

    <!-- Certificate trust modal (shown before setup for remote HTTPS clients) -->
    <CertTrustModal
      v-model="showCertModal"
      @continue="handleCertContinue"
    />

    <!-- Project Review Modal (same as Dashboard) -->
    <ProjectReviewModal
      :show="showReviewModal"
      :project-id="reviewProjectId"
      :product-id="reviewProductId"
      @close="showReviewModal = false; reviewProjectId = null; reviewProductId = null"
    />

    <!-- FE-9200: wizard = setup mode; TutorialOverlay = the post-setup tour.
         Both stay mounted and gate on modelValue (wizard timers unchanged). -->
    <SetupWizardOverlay
      :model-value="showSetupOverlay && setupOverlayMode === 'setup'"
      :current-step="setupStep"
      :selected-tools="setupSelectedTools"
      :setup-step-completed="setupStepCompleted"
      :is-rerun="forceSetupMode"
      :mode="setupOverlayMode"
      @update:model-value="showSetupOverlay = $event"
      @update:current-step="setupStep = $event"
      @step-complete="handleStepComplete"
      @dismiss="handleDismiss"
    />
    <TutorialOverlay
      :model-value="showSetupOverlay && setupOverlayMode === 'learning'"
      @update:model-value="showSetupOverlay = $event"
      @dismiss="handleDismiss"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useProductStore } from '@/stores/products'
import { useProjectStore } from '@/stores/projects'
import { getAgentColor } from '@/config/agentColors'
import api from '@/services/api'
import { PRODUCT_NAME } from '@/branding'
import GilMascot from '@/components/GilMascot.vue'
import SetupWizardOverlay from '@/components/setup/SetupWizardOverlay.vue'
import TutorialOverlay from '@/components/tutorial/TutorialOverlay.vue'
import CertTrustModal from '@/components/setup/CertTrustModal.vue'
import RecentProjectsList from '@/components/dashboard/RecentProjectsList.vue'
import ProjectReviewModal from '@/components/projects/ProjectReviewModal.vue'
import configService from '@/services/configService'
import { recordCertTrustDismissal } from '@/utils/certTrustPreference'
import { PROJECT_TEMPLATES } from '@/composables/projectTemplates'
import { useToast } from '@/composables/useToast'
import { useDeferredHomeData } from '@/composables/useDeferredHomeData'
import { useWelcomeGreeting } from '@/composables/useWelcomeGreeting'
import WelcomeQuickGrid from './welcome/WelcomeQuickGrid.vue'
import WelcomeTeamSection from './welcome/WelcomeTeamSection.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const productStore = useProductStore()
const projectStore = useProjectStore()
const { showToast } = useToast()

// Step-4 template card state
const busyTemplateId = ref(null)

// Certificate trust modal state
const showCertModal = ref(false)
const certModalDismissed = ref(false)
const pendingSetupOpen = ref(false)

// Setup wizard state
const showSetupOverlay = ref(false)
const setupStep = ref(0)
const forceSetupMode = ref(false)

const setupComplete = computed(() => userStore.currentUser?.setup_complete ?? false)
const learningComplete = computed(() => userStore.currentUser?.learning_complete ?? false)
const setupOverlayMode = computed(() => {
  if (forceSetupMode.value) return 'setup'
  return setupComplete.value ? 'learning' : 'setup'
})
const setupStepCompleted = computed(() => userStore.currentUser?.setup_step_completed ?? 0)
const setupSelectedTools = computed(() => userStore.currentUser?.setup_selected_tools ?? [])

const setupCtaLabel = computed(() => {
  if (setupStepCompleted.value > 0) return 'Resume Setup'
  return 'Getting Started'
})

async function handleStepComplete({ step, data }) {
  if (step === 0 && data.tools) {
    await userStore.updateSetupState({
      setup_selected_tools: data.tools,
      setup_step_completed: 1,
    })
  } else if (step === 1) {
    await userStore.updateSetupState({
      setup_step_completed: 2,
    })
  } else if (step === 2) {
    await userStore.updateSetupState({
      setup_step_completed: 3,
    })
  } else if (step === 3 && data.setup_complete) {
    await userStore.updateSetupState({
      setup_complete: true,
      setup_step_completed: 4,
    })
    showSetupOverlay.value = false

    if (!forceSetupMode.value) {
      setTimeout(() => {
        showSetupOverlay.value = true
      }, 1600)
    } else if (data.route) {
      router.push(data.route)
    }
  }
}

async function handleDismiss() {
  const wasFirstTimeFinish = setupStep.value >= 3 && !setupComplete.value && !forceSetupMode.value
  const wasLearningMode = setupOverlayMode.value === 'learning'
  showSetupOverlay.value = false
  forceSetupMode.value = false

  if (wasLearningMode && !learningComplete.value) {
    await userStore.updateSetupState({ learning_complete: true })
  }

  if (wasFirstTimeFinish || (setupStep.value >= 3 && !setupComplete.value)) {
    await userStore.updateSetupState({
      setup_complete: true,
      setup_step_completed: 4,
    })

    if (wasFirstTimeFinish) {
      setTimeout(() => {
        showSetupOverlay.value = true
      }, 600)
    }
  }
}

function handleCertContinue(dontShowAgain = false) {
  certModalDismissed.value = true
  recordCertTrustDismissal(dontShowAgain)
  if (pendingSetupOpen.value) {
    pendingSetupOpen.value = false
    showSetupOverlay.value = true
  }
}

function openSetupWithCertGate() {
  if (shouldShowCertModal()) {
    pendingSetupOpen.value = true
    showCertModal.value = true
  } else {
    showSetupOverlay.value = true
  }
}

function shouldShowCertModal() {
  if (localStorage.getItem('cert_modal_never') === '1') return false
  if (sessionStorage.getItem('cert_modal_dismissed') === '1') return false
  if (certModalDismissed.value) return false
  const config = configService.getRawConfig()
  if (!config) return false
  return config.api?.ssl_enabled === true && config.api?.is_remote_client === true
}

defineExpose({ shouldShowCertModal, handleCertContinue })

// Template data
const templates = ref([])
// Pre-load placeholder; overwritten by the active-count API's max_slots (the
// server-enforced total: 15 user-managed + 1 reserved orchestrator = 16).
const totalSlots = ref(16)

const activeTemplates = computed(() =>
  templates.value
    .filter(t => t.is_active)
    .map(t => {
      const color = getAgentColor(t.role || t.name)
      return {
        id: t.id,
        name: t.display_name || t.name,
        description: t.short_description || color.description,
        badge: color.badge,
        color: color.hex,
      }
    })
)

const emptySlots = computed(() => Math.max(0, totalSlots.value - activeTemplates.value.length - 1))
const hasStaleAgents = computed(() => templates.value.some(t => t.is_active && t.may_be_stale))

// Quick-launch cards — adapt to product state
const hasActiveProduct = computed(() => !!productStore.activeProduct)
const hasAnyProduct = computed(() => productStore.hasProducts)
const activeProjectCount = computed(() => projectStore.activeProjects?.length ?? 0)
const hasAnyProject = computed(() => (projectStore.projects?.length ?? 0) > 0)

// Onboarding-aware quick launch card definitions
const setupCard = {
  title: 'Quick Setup',
  description: `Connect your AI coding tools and configure ${PRODUCT_NAME}.`,
  icon: 'mdi-rocket-launch',
  iconBg: 'rgba(255,195,0,0.1)',
  iconColor: 'var(--brand-yellow)',
  accent: 'var(--brand-yellow)',
  action: openSetupWithCertGate,
}

const learnCard = {
  title: 'Learn',
  description: 'Understand products, projects, agents, and slash commands.',
  icon: 'mdi-book-open-variant',
  iconBg: 'rgba(94,196,142,0.12)',
  iconColor: getAgentColor('documenter').hex,
  accent: getAgentColor('documenter').hex,
  action: () => { showSetupOverlay.value = true },
}

const dashboardCard = {
  title: 'Dashboard',
  description: 'View system stats, recent activity, and orchestration metrics at a glance.',
  icon: 'mdi-view-dashboard-outline',
  iconBg: 'rgba(109,179,228,0.12)',
  iconColor: getAgentColor('implementer').hex,
  accent: getAgentColor('implementer').hex,
  to: '/Dashboard',
}

const newProjectCard = computed(() => ({
  title: 'New Project',
  description: 'Create and launch a project with your Agent team or directly from your AI tool.',
  icon: 'mdi-plus-circle-outline',
  iconBg: 'rgba(255,195,0,0.1)',
  iconColor: 'var(--brand-yellow)',
  accent: 'var(--brand-yellow)',
  badge: '/giljo add project',
  to: '/Projects',
  attention: !hasAnyProject.value,
}))

const newProductCard = computed(() => ({
  title: 'New Product',
  description: 'Define a product to give your AI agents full context about what they\'re building.',
  icon: 'mdi-package-variant-closed',
  iconBg: 'rgba(255,195,0,0.1)',
  iconColor: 'var(--brand-yellow)',
  accent: 'var(--brand-yellow)',
  to: '/Products',
  attention: true,
}))

const activateProductCard = computed(() => ({
  title: 'Activate Product',
  description: 'You have a product but it\'s not active. Activate it to start creating projects.',
  icon: 'mdi-play-circle-outline',
  iconBg: 'rgba(255,195,0,0.1)',
  iconColor: 'var(--brand-yellow)',
  accent: 'var(--brand-yellow)',
  to: '/Products',
  attention: true,
}))

const taskBoardCard = {
  title: 'Task Board',
  description: 'Track technical debt, scope creep captures, and tasks or directly from your AI tool.',
  icon: 'mdi-clipboard-check-outline',
  iconBg: 'rgba(172,128,204,0.12)',
  iconColor: getAgentColor('reviewer').hex,
  accent: getAgentColor('reviewer').hex,
  badge: '/giljo add task',
  to: '/Tasks',
}

const lookupCard = {
  title: 'Look Up',
  description: 'Read projects and tasks from your AI tool — filter by status, type, or priority.',
  icon: 'mdi-magnify',
  iconBg: 'var(--agent-documenter-tinted)',
  iconColor: 'var(--agent-documenter-primary)',
  accent: 'var(--agent-documenter-primary)',
  badge: '/giljo',
  to: '/Tasks',
}

const activeProjectsCard = computed(() => ({
  title: 'Active Projects',
  description: 'Monitor running orchestrations, agent status, and real-time progress.',
  icon: 'mdi-play-circle-outline',
  iconBg: 'rgba(109,179,228,0.12)',
  iconColor: getAgentColor('implementer').hex,
  accent: getAgentColor('implementer').hex,
  badge: `${activeProjectCount.value} active`,
  to: '/launch?via=jobs',
}))

const templateCards = computed(() =>
  PROJECT_TEMPLATES.map((tmpl) => ({
    id: `template-${tmpl.id}`,
    templateId: tmpl.id,
    isTemplate: true,
    busy: busyTemplateId.value === tmpl.id,
    title: tmpl.cardTitle,
    description: tmpl.cardSubtitle,
    icon: tmpl.icon,
    iconBg: 'rgba(109,179,228,0.12)',
    iconColor: getAgentColor('implementer').hex,
    accent: getAgentColor('implementer').hex,
    action: () => createFromTemplate(tmpl),
  }))
)

async function createFromTemplate(tmpl) {
  if (busyTemplateId.value) return
  const productId = productStore.activeProduct?.id || productStore.effectiveProductId
  if (!productId) {
    showToast({
      message: 'No active product — activate a product before creating a project.',
      color: 'error',
    })
    return
  }
  busyTemplateId.value = tmpl.id
  try {
    await projectStore.createProject({
      name: tmpl.projectName,
      description: tmpl.projectDescription,
      product_id: productId,
    })
    busyTemplateId.value = null
    router.push('/Projects')
  } catch (err) {
    busyTemplateId.value = null
    showToast({
      message: err?.message || 'Failed to create project from template',
      color: 'error',
    })
  }
}

function onCardClick(card) {
  if (card.busy) return
  if (typeof card.action === 'function') {
    card.action()
    return
  }
  if (card.to) {
    router.push(card.to)
  }
}

// Onboarding phase: true until user has at least one product AND one project
const onboardingComplete = computed(() => hasActiveProduct.value && hasAnyProject.value)

const quickCards = computed(() => {
  if (!setupComplete.value) {
    return [setupCard]
  }
  if (!learningComplete.value) {
    return [learnCard]
  }
  if (!hasAnyProduct.value) {
    return [newProductCard.value]
  }
  if (!hasActiveProduct.value) {
    return [activateProductCard.value]
  }
  if (!hasAnyProject.value) {
    return [newProjectCard.value, ...templateCards.value]
  }
  if (activeProjectCount.value > 0) {
    return [activeProjectsCard.value, dashboardCard, taskBoardCard, lookupCard]
  }
  return [dashboardCard, newProjectCard.value, taskBoardCard, lookupCard]
})

// Recent projects (from dashboard API)
const recentProjects = ref([])

function getUserDisplayName() {
  const user = userStore.currentUser
  return user?.first_name || user?.full_name || user?.username || user?.email?.split('@')[0] || 'Friend'
}

// FE-6059: defer Home's Tools-domain reads (agent templates) off the cold first
// paint — loaded lazily when the team section renders. FE-9202: the onboarding
// nudges moved into the unified banner strip (SystemStatusBanner), so Home no
// longer loads git/serena status or evaluates the reminder gates here.
useDeferredHomeData({
  onboardingComplete,
  showIntegReminder: ref(false),
  templates,
  totalSlots,
})

const showReviewModal = ref(false)
const reviewProjectId = ref(null)
const reviewProductId = ref(null)

function handleReviewProject(project) {
  reviewProjectId.value = project.id || project.project_id
  reviewProductId.value = project.product_id || null
  if (reviewProjectId.value) showReviewModal.value = true
}

// Version
const appVersion = ref('')

// Greeting via composable (FE-6006)
const firstName = computed(() => {
  const name = getUserDisplayName()
  return String(name).split(' ')[0]
})
const { fullGreeting } = useWelcomeGreeting({ firstName })

onMounted(async () => {
  try {
    await configService.fetchConfig()
    appVersion.value = configService.getVersion()
  } catch { /* config may fail on first load */ }

  if (route.query.openGuide === 'true') {
    showSetupOverlay.value = true
    router.replace({ path: '/home' })
  } else if (route.query.openSetup === 'true' || !setupComplete.value) {
    forceSetupMode.value = route.query.openSetup === 'true'
    setupStep.value = Math.min(setupStepCompleted.value, 3)

    if (shouldShowCertModal()) {
      pendingSetupOpen.value = true
      showCertModal.value = true
    } else {
      showSetupOverlay.value = true
    }

    if (route.query.openSetup) {
      router.replace({ path: '/home' })
    }
  }

  // FE-6058: fire independent reads in parallel instead of a 6-call serial
  // waterfall. Each call still swallows its own error exactly as before; only
  // the dashboard read depends on products (via effectiveProductId), so it
  // chains off the products fetch. This cuts the home-view content delay from
  // the SUM of every round-trip down to roughly the slowest single one.
  const productsLoaded = productStore.fetchProducts().catch(() => {})

  // FE-6059: agent-template reads (api.templates.list / activeCount) are no
  // longer fired here — they are deferred behind the onboardingComplete watcher
  // so the "Your Team" section loads them only when it will actually render.
  await Promise.allSettled([
    productsLoaded,
    projectStore.fetchProjects().catch(() => {}),
    // Dashboard read genuinely depends on products being loaded first.
    productsLoaded.then(() => {
      if (setupComplete.value && productStore.effectiveProductId) {
        return api.stats
          .getDashboard(productStore.effectiveProductId)
          .then((response) => {
            recentProjects.value = response.data?.recent_projects || []
          })
          .catch(() => {})
      }
    }),
  ])
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;
.welcome-wrapper {
  position: relative;
  min-height: 100%;
}

.welcome-atmosphere {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse 700px 500px at 50% 15%, rgba(255,195,0,0.04) 0%, transparent 60%),
    radial-gradient(ellipse 500px 500px at 80% 60%, rgba(109,179,228,0.03) 0%, transparent 60%);
}

.welcome-page {
  position: relative;
  z-index: 1;
  max-width: 960px;
  margin: 0 auto;
  padding: 40px 32px 48px;
}

/* ═══ HERO ═══ */
.hero {
  text-align: center;
  margin-bottom: 36px;
  animation: fadeSlideDown 0.6s ease-out;
}

.hero-mascot {
  position: relative;
  display: inline-block;
  width: 88px;
  height: 100px;
  margin-bottom: 20px;
}

.hero-mascot-inner {
  position: relative;
  z-index: 1;
  filter: drop-shadow(0 0 14px rgba(255,195,0,0.35)) drop-shadow(0 0 36px rgba(107,207,127,0.15));
  animation: mascotFloat 4s ease-in-out infinite;
}

.hero-mascot-glow {
  position: absolute;
  inset: -20px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255,217,61,0.14) 0%, rgba(107,207,127,0.06) 50%, transparent 70%);
  z-index: 0;
  animation: glowPulse 4s ease-in-out infinite;
}

.hero-greeting {
  font-size: 1.65rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 6px;
  color: var(--color-text-primary);
}

.hero-subtitle {
  font-size: 0.88rem;
  color: var(--text-secondary);
  font-weight: 300;
  max-width: 480px;
  margin: 0 auto;
  line-height: 1.55;
}

.hero-subtitle-dim {
  opacity: 0.7;
}

/* ═══ SECTION LABEL ═══ */
.section-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  margin-bottom: 12px;
  font-weight: 500;
}

/* ═══ SETUP CTA ═══ */
.setup-cta-section {
  margin-bottom: 36px;
  animation: fadeSlideUp 0.45s ease-out 0.42s both;
}

.setup-cta {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  background: rgb(var(--v-theme-surface));
  border-radius: $border-radius-rounded;
  cursor: pointer;
  transition: all $transition-normal;
}

.setup-cta:hover {
  transform: translateY(-2px);
  box-shadow: inset 0 0 0 1px var(--smooth-border-color, rgba(255,255,255,0.10)), 0 6px 16px -4px rgba(0,0,0,0.25);
}

.setup-cta-text {
  flex: 1;
}

.setup-cta-title {
  font-size: 0.92rem;
  font-weight: 600;
  margin-bottom: 2px;
}

.setup-cta-desc {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

/* ═══ RECENT PROJECTS ═══ */
.recent-projects-section {
  margin-bottom: 36px;
  animation: fadeSlideUp 0.45s ease-out 0.42s both;
}

.recent-projects-panel {
  background: rgb(var(--v-theme-surface));
  border-radius: $border-radius-rounded;
  overflow: hidden;
}

.rp-header {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.rp-title {
  font-size: 0.92rem;
  font-weight: 600;
}

.rp-link {
  font-size: 0.68rem;
  color: $yellow;
  cursor: pointer;
  font-weight: 500;
  opacity: 0.7;
  text-decoration: none;
}

.rp-link:hover {
  opacity: 1;
}

/* ═══ FOOTER ═══ */
.page-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding-top: 20px;
  border-top: 1px solid rgba(255,255,255,0.04);
  animation: fadeSlideUp 0.45s ease-out 0.55s both;
}

.footer-item {
  font-size: 0.68rem;
  color: var(--text-muted);
}

.footer-item.mono {
  font-family: 'IBM Plex Mono', monospace;
}

/* ═══ ANIMATIONS ═══ */
@keyframes fadeSlideDown {
  from { opacity: 0; transform: translateY(-14px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeSlideUp {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes mascotFloat {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-4px); }
}

@keyframes glowPulse {
  0%, 100% { opacity: 0.8; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.06); }
}

/* ═══ RESPONSIVE ═══ */
@media (max-width: 960px) {
  .welcome-page {
    padding: 32px 20px 40px;
  }
}
</style>
